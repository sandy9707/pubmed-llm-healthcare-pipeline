import pandas as pd
import json
import requests
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

INPUT_FILE = "/Volumes/lev/Documents/待完成任务/20260212_摘要下载/2_extracted_data/pubmed_summary_4cols.xlsx"
OUT_DIR = "/Volumes/lev/Documents/待完成任务/20260212_摘要下载/4_final_results"
# 命名有所更新，以区分以前的纯文本结果
OUT_FILE_NAME = "pubmed_summary_4cols_filtered_json.xlsx"
OUTPUT_FILE = os.path.join(OUT_DIR, OUT_FILE_NAME)

OLLAMA_API_URL = "http://10.9.65.31:11434/api/chat"

MODELS_TO_TEST = [
    ("qwen2.5:7b", "qwen2.5_7b", 60),
    ("dolphin3:8b", "dolphin3_8b", 60),
]

# === 融合版 Prompt: Modified PICOS + Keywords ===
PROMPT_TEMPLATE = """
# Role
你是一名医学信息学领域的系统综述筛选专家。你的任务是精准筛选出关于 **"大语言模型(LLM)/生成式AI/智能体(Agent)在医疗领域应用"** 的文献。

# Evaluation Framework (Modified PICOS)
请严格按照以下三个维度提取信息并进行逻辑判断：

1. **Intervention (I) - 技术干预 [核心判据]**:
   - **判定标准**: 文献必须涉及基于 **Transformer 的生成式模型** 或 **AI Agent**。
   - **包含词**: LLM, Large Language Model, Generative AI, RAG, Foundation Model, Agent, In-context Learning, CoT.
   - **模型白名单**: GPT-3/3.5/4, ChatGPT, Llama, Claude, Gemini, PaLM, Med-PaLM, Mistral, Qwen 等。
   - **排除词 (Exclusion)**: 如果仅使用 BERT, RoBERTa, LSTM, CNN, SVM, Random Forest 等**传统判别式模型**，且未涉及生成任务，判定为【否】。
   - **任务**: 提取文中使用的具体模型名称或技术类别。

2. **Population/Context (P) - 应用场景**:
   - **判定标准**: 必须发生在医疗、临床、公共卫生、医学教育、生物医学研究等背景下。
   - **任务**: 提取具体的应用对象（如：电子病历 EHR、医学影像报告、患者问答、药物研发）。

3. **Study Design (S) - 研究类型**:
   - **任务**: 判断文章类型（如：实证研究、系统开发、综述、社论/观点）。
   - *注意*: 除非文章完全没有具体技术细节（纯吹水），否则只要 I 和 P 符合，即可纳入。

# Decision Logic (决策逻辑)
- **YES**: (Intervention 符合生成式AI定义) AND (Context 属于医疗领域)。
- **NO**: (Intervention 仅为传统NLP/ML) OR (Context 非医疗)。
- **UNCERTAIN**: 摘要信息不足以判断模型类型，或者使用了模糊的 "AI" 一词而未指明技术。

# Output Format (JSON Only)
请仅输出一个合法的 JSON 对象，不要包含 Markdown 格式标记（如 ```json ... ```）：
{{
    "analysis": {{
        "Intervention_Model": "提取到的模型名称（如 'GPT-4', 'Llama 2'）或 'Traditional NLP' / 'None'",
        "Context_Domain": "提取到的具体场景（如 '放射科报告生成'）",
        "Study_Type": "Empirical Study / Review / Commentary"
    }},
    "reasoning": "用一句话简述理由。例如：'使用了生成式模型(Llama 2)处理临床病历(EHR)，符合纳入标准。' 或 '仅使用了BERT进行分类，属于传统NLP，排除。'",
    "is_relevant": "是" | "否" | "不确定"
}}

# Input Data
标题: {title}
摘要: {abstract}
"""


def extract_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()

    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1:
        text = text[start_idx : end_idx + 1]

    return json.loads(text)


def call_ollama(idx, model_name, suffix, prompt, timeout):
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, "num_predict": 1024},
    }

    start_time = time.time()
    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=timeout)
        response.raise_for_status()

        result_json = response.json()
        raw_content = result_json.get("message", {}).get("content", "").strip()
        elapsed = time.time() - start_time

        try:
            parsed = extract_json(raw_content)
            analysis = parsed.get("analysis", {})

            results = {
                "RawJSON": raw_content,
                "Intervention_Model": analysis.get("Intervention_Model", ""),
                "Context_Domain": analysis.get("Context_Domain", ""),
                "Study_Type": analysis.get("Study_Type", ""),
                "Reasoning": parsed.get("reasoning", ""),
                "Is_Relevant": parsed.get("is_relevant", "Error"),
            }
            return idx, suffix, results, elapsed
        except json.JSONDecodeError:
            err_res = {"RawJSON": raw_content, "Is_Relevant": "Error: JSON Parse"}
            return idx, suffix, err_res, elapsed

    except requests.exceptions.Timeout:
        elapsed = time.time() - start_time
        return idx, suffix, {"Is_Relevant": "Timeout"}, elapsed
    except Exception as e:
        elapsed = time.time() - start_time
        return idx, suffix, {"Is_Relevant": f"Error: {str(e)}"}, elapsed


def main():
    print(f"Loading data...")
    if os.path.exists(OUTPUT_FILE):
        print(f"Found existing output file {OUTPUT_FILE}. Loading to resume/retry...")
        df = pd.read_excel(OUTPUT_FILE)
    elif os.path.exists(INPUT_FILE):
        print(f"Loading base data from {INPUT_FILE}...")
        df = pd.read_excel(INPUT_FILE)
    else:
        print(f"Error: file not found {INPUT_FILE}")
        return

    print(f"Total rows in dataset: {len(df)}")

    # 包含用户需要的基准列和JSON细化列
    key_columns = [
        "Is_Relevant",
        "Intervention_Model",
        "Context_Domain",
        "Study_Type",
        "Reasoning",
        "RawJSON",
    ]

    for _, suffix, _ in MODELS_TO_TEST:
        for k in key_columns:
            if f"{k}_{suffix}" not in df.columns:
                df[f"{k}_{suffix}"] = ""
        if f"Time_{suffix}(s)" not in df.columns:
            df[f"Time_{suffix}(s)"] = 0.0

    if "Consistency" not in df.columns:
        df["Consistency"] = ""

    os.makedirs(OUT_DIR, exist_ok=True)

    print(
        "Starting smart semantic testing with the Modified PICOS JSON Extraction CoT prompt..."
    )
    start_time = time.time()

    # Identify rows that need processing
    rows_to_process = []
    for idx, row in df.iterrows():
        consistency = str(row.get("Consistency", "")).strip()
        # If consistency is Failed, empty, nan, or Error, we should process it
        if consistency in ["Failed", "", "nan", "None"] or "Error" in consistency:
            rows_to_process.append(idx)

    print(f"Rows needing evaluation (Failed or New): {len(rows_to_process)}")

    if len(rows_to_process) == 0:
        print("All rows already successfully processed!")
        return

    total_calls_needed = len(rows_to_process) * len(MODELS_TO_TEST)
    completed_new_calls = 0
    completions_tracker = {i: 0 for i in df.index}

    with ThreadPoolExecutor(max_workers=14) as executor:
        # 使用块处理来防止内存/网络溢出，只针对需要重试的行
        for chunk_idx in range(0, len(rows_to_process), 50):
            chunk_indices = rows_to_process[chunk_idx : chunk_idx + 50]
            chunk_df = df.loc[chunk_indices]
            futures = []

            for idx, row in chunk_df.iterrows():
                title = str(row.get("TI", ""))
                abstract = str(row.get("AB", ""))

                if title == "nan":
                    title = ""
                if abstract == "nan":
                    abstract = ""

                prompt = PROMPT_TEMPLATE.format(title=title, abstract=abstract)

                for model_name, suffix, timeout in MODELS_TO_TEST:
                    futures.append(
                        executor.submit(
                            call_ollama, idx, model_name, suffix, prompt, timeout
                        )
                    )

            # 等待本块完成
            for future in as_completed(futures):
                idx, suffix, results_dict, elapsed = future.result()

                for dict_key, dict_val in results_dict.items():
                    df.at[idx, f"{dict_key}_{suffix}"] = dict_val

                df.at[idx, f"Time_{suffix}(s)"] = round(elapsed, 2)

                completions_tracker[idx] += 1
                completed_new_calls += 1

                if completions_tracker[idx] == len(MODELS_TO_TEST):
                    answers = [
                        str(df.at[idx, f"Is_Relevant_{s}"])
                        for _, s, _ in MODELS_TO_TEST
                    ]

                    if any("Error" in a or "Timeout" in a for a in answers):
                        df.at[idx, "Consistency"] = "Failed"
                    elif "不确定" in answers:
                        df.at[idx, "Consistency"] = "Ambiguous"
                    elif len(set(answers)) == 1:
                        df.at[idx, "Consistency"] = "Match"
                    else:
                        df.at[idx, "Consistency"] = "Mismatch"

            print(f"Progress: {completed_new_calls}/{total_calls_needed} fresh queries served.")

            # 排序导出的列
            base_cols = ["PMID", "TI", "AB", "DP"]
            dynamic_cols = [
                c for c in df.columns if c not in base_cols and c != "Consistency"
            ]
            final_cols = (
                [c for c in base_cols if c in df.columns]
                + dynamic_cols
                + ["Consistency"]
            )

            df[final_cols].to_excel(OUTPUT_FILE, index=False)

    print(f"\nProcessing Completed in {time.time() - start_time:.2f} seconds!")
    match_count = (df["Consistency"] == "Match").sum()
    mismatch_count = (df["Consistency"] == "Mismatch").sum()
    print(
        f"Row Level Consistency (Based strictly on Is_Relevant core score) [Matches]: {match_count}"
    )
    print(
        f"Row Level Consistency (Based strictly on Is_Relevant core score) [Mismatches]: {mismatch_count}"
    )
    print(f"Saved highly-structured analytical results to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
