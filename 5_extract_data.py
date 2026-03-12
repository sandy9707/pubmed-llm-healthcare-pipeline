import pandas as pd
import json
import requests
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

INPUT_FILE = "/Volumes/lev/Documents/待完成任务/20260212_摘要下载/4_final_results/pubmed_summary_4cols_filtered_json.xlsx"
OUT_DIR = "/Volumes/lev/Documents/待完成任务/20260212_摘要下载/5_final_extraction"
OUT_FILE_NAME = "pubmed_extracted_details.xlsx"
OUTPUT_FILE = os.path.join(OUT_DIR, OUT_FILE_NAME)

OLLAMA_API_URL = "http://10.9.65.31:11434/api/chat"

MODELS_TO_TEST = [
    ("qwen2.5:7b", "qwen2.5_7b", 300),
    ("dolphin3:8b", "dolphin3_8b", 300),
]

EXTRACTION_PROMPT_TEMPLATE = """
# Role
你是一名严谨的医学数据科学家。你的任务是从已经被初步判定为“相关”的文献摘要中，结构化地提取关键信息。

# Task
请阅读以下文献的标题和摘要，并严格按照规则提取以下 10 个字段的信息。

# Extraction Rules (提取规则)

1. **tech_category (使用技术)**: 
   - 只能从以下选项中选择：["LLM", "Agent", "其他"]。必须输出为包含字符串的JSON数组。
   - 示例: ["LLM", "Agent"] 或 ["其他"]

2. **other_tech (其他技术具体内容)**: 
   - 如果上一项包含了“其他”，请在这里写出具体的其他技术（如：Knowledge Graph, Computer Vision, 传统机器学习）。
   - 如果没有，严格输出 ["无"]。必须输出为包含字符串的JSON数组。

3. **domain_category (对应领域)**: 
   - 只能从以下选项中选择：["医疗", "临床", "其他"]。
   - **区分指南**：
     - **临床 (Clinical)**: 涉及医生与患者的直接交互，如：疾病诊断、治疗方案推荐、手术辅助、临床影像报告生成、电子病历(EHR)信息提取。
     - **医疗 (Healthcare)**: 宏观或非直接面对患者的场景，如：药物研发、公共卫生、医疗管理、通用医学问答。
   - 必须输出为包含字符串的JSON数组。

4. **other_domain (其他领域具体内容)**: 
   - 如果上一项包含了“其他”，请写明具体场景（如：医学教育, 医学写作, 护理管理）。
   - 如果没有，严格输出 ["无"]。必须输出为包含字符串的JSON数组。

5. **model_names (使用模型名称)**: 
   - 提取文中具体使用的基座模型名称（如：GPT-4, Llama-2, ChatGLM, Med-PaLM）。
   - 必须输出为包含字符串的JSON数组。如果没有提到具体模型名，严格输出 ["未提及"]。

6. **problem_solved (具体解决问题)**: 
   - 用一句精炼的话总结该研究“试图用XX技术解决什么具体问题”。必须为单条字符串。
   - 示例："利用大模型从非结构化放射学报告中自动提取肿瘤特征。"

7. **has_secondary_dev (是否存在大模型二次开发)**: 
   - 只能输出：是 / 否 / 不确定。必须为单条字符串。
   - **判定为“是”的条件**：文章不仅调用了基础API，还进行了针对性优化，包括但不限于：构建专有数据集、使用复杂的提示工程(Prompt Engineering, 如CoT, Few-shot)、微调(Fine-tuning, LoRA)、检索增强生成(RAG)、或者提出了新的医疗专属评估指标/基准(Benchmark)。

8. **secondary_dev_methods (二次开发的具体方式)**: 
   - 如果上一项为“否”或“不确定”，严格输出 ["无"]。
   - 如果为“是”，请根据文中内容，归纳使用了哪些具体的优化方式。请尽量使用以下标准术语进行归纳总结，必须输出为包含字符串的JSON数组：
     - [数据集构建]: 构建了专门的医学问答/评估数据集
     - [提示策略]: 如 思维链(CoT)、少样本学习(Few-shot)、角色扮演等
     - [模型微调]: 如 指令微调(SFT)、LoRA、参数高效微调(PEFT)
     - [RAG增强]: 引入外部知识库、向量检索
     - [研究扩展]: 提出了新的评估指标、构建了新的多Agent评估框架

9. **is_review (是否综述)**:
   - 只能输出：是 / 否 / 不确定。必须为单条字符串。判断文章是否为主要基于文献总结的综述。

10. **research_methodology (大模型研究方法)**:
    - 只能从以下选项中选择（单选，必须为单条字符串）：
      - 综述类研究
      - 评估类研究 (仅用现成模型评估性能)
      - 开发与评估相结合的研究 (自己微调/RAG/设计Agent并测试)
      - 随机对照试验评估 (进行临床/统计学上的RCT对照实验)
      - 其他

# Output Format (JSON Only)
请仅输出一个合法的 JSON 对象，不要包含 Markdown 格式标记（如 ```json ... ```）：
{{
    "tech_category": ["xxx"],
    "other_tech": ["xxx"],
    "domain_category": ["xxx"],
    "other_domain": ["xxx"],
    "model_names": ["xxx"],
    "problem_solved": "xxx",
    "has_secondary_dev": "xxx",
    "secondary_dev_methods": ["xxx"],
    "is_review": "xxx",
    "research_methodology": "xxx"
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

def flatten_array(val):
    if isinstance(val, list):
        return ";".join([str(v) for v in val])
    return str(val)

def call_ollama(idx, model_name, suffix, prompt, timeout, max_retries=3):
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, "num_predict": 1024},
    }

    start_time = time.time()
    for attempt in range(max_retries):
        try:
            response = requests.post(OLLAMA_API_URL, json=payload, timeout=timeout)
            response.raise_for_status()

            result_json = response.json()
            raw_content = result_json.get("message", {}).get("content", "").strip()

            try:
                parsed = extract_json(raw_content)
                results = {
                    "RawJSON_Ext": raw_content,
                    "tech_category": flatten_array(parsed.get("tech_category", [])),
                    "other_tech": flatten_array(parsed.get("other_tech", [])),
                    "domain_category": flatten_array(parsed.get("domain_category", [])),
                    "other_domain": flatten_array(parsed.get("other_domain", [])),
                    "model_names": flatten_array(parsed.get("model_names", [])),
                    "problem_solved": str(parsed.get("problem_solved", "")),
                    "has_secondary_dev": str(parsed.get("has_secondary_dev", "")),
                    "secondary_dev_methods": flatten_array(parsed.get("secondary_dev_methods", [])),
                    "is_review": str(parsed.get("is_review", "")),
                    "research_methodology": str(parsed.get("research_methodology", "")),
                    "Status": "Done"
                }
                return idx, suffix, results, time.time() - start_time
            except json.JSONDecodeError:
                if attempt == max_retries - 1:
                    err_res = {"RawJSON_Ext": raw_content, "Status": "Error: JSON Parse"}
                    return idx, suffix, err_res, time.time() - start_time

        except requests.exceptions.Timeout:
            if attempt == max_retries - 1:
                return idx, suffix, {"Status": "Timeout"}, time.time() - start_time
        except Exception as e:
            if attempt == max_retries - 1:
                return idx, suffix, {"Status": f"Error: {str(e)}"}, time.time() - start_time
            time.sleep(1)  # Brief pause before retrying

def main():
    print(f"Loading Phase 4 results from {INPUT_FILE}...")
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Step 4 output file not found -> {INPUT_FILE}")
        return

    # Load previously extracted step 4 data
    df_step4 = pd.read_excel(INPUT_FILE)
    
    # 筛选纳入标准：只要不是 (Qwen坚定认为="否" 且 Dolphin坚定认为="否") 的情况，全都纳入Phase 5深度抽取。
    # 考虑到4号脚本可能还有Failed的数据，也会保留下来尝试处理
    qwen_is_no = df_step4["Is_Relevant_qwen2.5_7b"].astype(str).str.strip() == "否"
    dolphin_is_no = df_step4["Is_Relevant_dolphin3_8b"].astype(str).str.strip() == "否"
    both_no = qwen_is_no & dolphin_is_no
    
    df_target = df_step4[~both_no].copy()
    print(f"Total rows in Step 4 dataset: {len(df_step4)}")
    print(f"Rows meeting inclusion criteria (Not fully rejected by both models): {len(df_target)}")

    # 检查是否有之前已经跑到一半的结果文件进行断点续传
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(OUTPUT_FILE):
        print(f"Found existing output file {OUTPUT_FILE}. Loading to resume/retry extraction...")
        df_target = pd.read_excel(OUTPUT_FILE)
    else:
        print("Starting fresh dataset extraction...")

    key_columns = [
        "Status",
        "tech_category", "other_tech", 
        "domain_category", "other_domain", 
        "model_names", "problem_solved", 
        "has_secondary_dev", "secondary_dev_methods", 
        "is_review", "research_methodology", 
        "RawJSON_Ext"
    ]

    for _, suffix, _ in MODELS_TO_TEST:
        for k in key_columns:
            if f"{k}_{suffix}" not in df_target.columns:
                df_target[f"{k}_{suffix}"] = ""
        if f"ExtTime_{suffix}(s)" not in df_target.columns:
            df_target[f"ExtTime_{suffix}(s)"] = 0.0

    print("Starting smart structural feature extraction with 10 dimensions...")
    start_time = time.time()

    # Identify rows that need processing inside df_target
    rows_to_process = []
    for idx, row in df_target.iterrows():
        # 我们用模型1的Status做基准来寻找残缺的项
        qwen_status = str(row.get("Status_qwen2.5_7b", "")).strip()
        dolphin_status = str(row.get("Status_dolphin3_8b", "")).strip()
        
        # If any of the target models have Failed, Empty, Timeout, or Error we process them
        if (qwen_status not in ["Done"]) or (dolphin_status not in ["Done"]):
            rows_to_process.append(idx)

    print(f"Rows pending extraction evaluation: {len(rows_to_process)}")

    if len(rows_to_process) == 0:
        print("All target rows already perfectly extracted! Check your output file.")
        return

    total_calls_needed = len(rows_to_process) * len(MODELS_TO_TEST)
    completed_new_calls = 0

    with ThreadPoolExecutor(max_workers=14) as executor:
        for chunk_idx in range(0, len(rows_to_process), 50):
            chunk_indices = rows_to_process[chunk_idx : chunk_idx + 50]
            chunk_df = df_target.loc[chunk_indices]
            futures = []

            for idx, row in chunk_df.iterrows():
                title = str(row.get("TI", ""))
                abstract = str(row.get("AB", ""))

                if title == "nan": title = ""
                if abstract == "nan": abstract = ""

                prompt = EXTRACTION_PROMPT_TEMPLATE.format(title=title, abstract=abstract)

                for model_name, suffix, timeout in MODELS_TO_TEST:
                    futures.append(
                        executor.submit(call_ollama, idx, model_name, suffix, prompt, timeout)
                    )

            for future in as_completed(futures):
                idx, suffix, results_dict, elapsed = future.result()

                for dict_key, dict_val in results_dict.items():
                    df_target.at[idx, f"{dict_key}_{suffix}"] = dict_val

                df_target.at[idx, f"ExtTime_{suffix}(s)"] = round(elapsed, 2)
                completed_new_calls += 1

            print(f"Extraction Progress: {completed_new_calls}/{total_calls_needed} model queries finished.")
            df_target.to_excel(OUTPUT_FILE, index=False)

    print(f"\nExtraction Pipeline Completed in {time.time() - start_time:.2f} seconds!")
    print(f"Saved structural database to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
