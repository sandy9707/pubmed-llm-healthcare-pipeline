import pandas as pd
import json
import requests
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= 配置区域 =================

# 输入文件路径 (保持您提供的路径)
INPUT_FILE = "/Volumes/lev/Documents/待完成任务/20260212_摘要下载/3_tuning_results/mismatched_200_details.xlsx"
# 输出目录
OUT_DIR = "/Volumes/lev/Documents/待完成任务/20260212_摘要下载/3_tuning_results"
# 输出文件名
OUT_FILE_NAME = "mismatched_200_comparison_optimized.xlsx"

# API 地址
OLLAMA_API_URL = "http://10.9.65.31:11434/api/chat"

# 待测试模型配置：(API中的模型名, 输出列后缀, 超时时间)
MODELS_TO_TEST = [
    ("qwen2.5:7b", "qwen2.5_7b", 60),
    ("dolphin3:8b", "dolphin3_8b", 60),
]

# === 核心：关键词扫描增强版 Prompt ===
PROMPT_TEMPLATE = """任务：判断以下文献是否属于“大语言模型(LLM)”、“生成式AI(GenAI)”或“智能体(Agent)”在医疗领域的应用。

请严格执行以下逻辑步骤进行判断：

第一步：关键词扫描（这是最重要的判断依据）
检查标题和摘要中是否【明确出现】以下关键词（不区分大小写）：
- 核心词：LLM, Large Language Model, Generative AI, GenAI, RAG, Agent, Foundation Model
- 具体模型名：ChatGPT, GPT-3, GPT-4, GPT-3.5, Llama, Gemini, Claude, Mistral, PaLM, BERT (注意：仅BERT通常属于传统NLP，除非明确提到生成任务), Transformer (需结合生成任务)
- 技术词：Prompt Engineering, Chain-of-Thought, In-context learning, Text generation, Chatbot (聊天机器人)

第二步：排除传统NLP
如果文献【仅】包含以下内容，而【没有】上述第一步的核心关键词，必须判定为“否”：
- 仅提到：Natural Language Processing (NLP), Machine Learning (ML), Deep Learning (DL)
- 仅涉及：Text mining (文本挖掘), Information extraction (信息提取), Classification (分类), Rule-based algorithms (基于规则), Electronic Health Records (EHR) data analysis (无生成式AI参与)

第三步：输出结果
- 如果符合第一步的关键词标准 -> 输出 "是"
- 如果属于第二步的传统NLP范畴 -> 输出 "否"
- 只有在完全无法确定时 -> 输出 "不确定"

注意：
1. 不要理会标题是否包含 "Artificial Intelligence"，重点看具体的模型和技术类型。
2. 必须且只能输出一个词："是"、"否" 或 "不确定"。

文献信息：
标题: {title}
摘要: {abstract}
"""

# ================= 功能函数 =================


def clean_model_output(content):
    """
    清洗模型输出，提取核心答案
    """
    content = content.strip()
    # 移除可能存在的标点符号
    clean_text = re.sub(r"[^\w\s]", "", content)

    if "不确定" in content:
        return "不确定", content

    # 优先匹配明确的“是”或“否”
    # 如果模型输出了 "答案：是"，或者 "判定：是"
    if content == "是" or content == "否":
        return content, ""

    if "是" in content and "否" not in content:
        return "是", content
    if "否" in content and "是" not in content:
        return "否", content

    # 如果含混不清
    return content, content


def call_ollama(pmid, model_name, suffix, prompt, timeout):
    """
    调用 Ollama API
    """
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "temperature": 0.0,  # 设置为0确保结果确定性
            "num_predict": 100,  # 限制输出长度
        },
    }

    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=timeout)
        response.raise_for_status()

        result_json = response.json()
        raw_content = result_json.get("message", {}).get("content", "").strip()

        short_answer, reasoning = clean_model_output(raw_content)
        return pmid, suffix, short_answer, reasoning

    except requests.exceptions.Timeout:
        return pmid, suffix, "Error: Timeout", ""
    except Exception as e:
        return pmid, suffix, f"Error: {str(e)}", ""


def main():
    # 1. 读取数据
    if not os.path.exists(INPUT_FILE):
        print(f"错误：找不到文件 {INPUT_FILE}")
        return

    print(f"正在读取文件: {INPUT_FILE}...")
    df = pd.read_excel(INPUT_FILE)
    print(f"共加载 {len(df)} 行数据。")

    # 准备结果容器
    results_map = {}  # {pmid: {suffix_output: val, suffix_reason: val}}

    # 2. 准备多线程任务
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = []

        for idx, row in df.iterrows():
            # 尝试获取标题和摘要，兼容不同列名
            title = str(row.get("Title", row.get("TI", "")))
            abstract = str(row.get("Abstract", row.get("AB", "")))

            # 获取PMID作为唯一标识
            pmid = str(row.get("PMID", idx))  # 如果没有PMID列，使用索引

            if pd.isna(title) or title == "nan":
                title = ""
            if pd.isna(abstract) or abstract == "nan":
                abstract = ""

            # 构建 Prompt
            prompt = PROMPT_TEMPLATE.format(title=title, abstract=abstract)

            # 初始化该行的结果存储
            if pmid not in results_map:
                results_map[pmid] = {
                    "PMID": pmid,
                    "Title": title,
                    "Abstract": abstract,
                    "Original_Row_Data": row,  # 保留原始数据以便合并
                }

            # 提交任务给每个模型
            for model_name, suffix, timeout in MODELS_TO_TEST:
                futures.append(
                    executor.submit(
                        call_ollama, pmid, model_name, suffix, prompt, timeout
                    )
                )

        # 3. 处理结果
        print("开始处理请求...")
        completed_count = 0
        total_tasks = len(futures)

        for future in as_completed(futures):
            r_pmid, r_suffix, r_answer, r_reason = future.result()

            # 存入结果字典
            results_map[r_pmid][f"Result_{r_suffix}"] = r_answer
            # 如果有额外解释，也可以存一列，虽然Prompt要求只输出于是/否
            if r_reason:
                results_map[r_pmid][f"Reason_{r_suffix}"] = r_reason

            completed_count += 1
            if completed_count % 10 == 0:
                print(f"进度: {completed_count}/{total_tasks}...")

    # 4. 转换为 DataFrame 并导出
    final_data = []
    for pmid, data in results_map.items():
        # 这里我们将新结果合并到一行中
        row_dict = {}
        # 优先保留原始列
        if "Original_Row_Data" in data:
            orig = data["Original_Row_Data"]
            for k, v in orig.items():
                row_dict[k] = v

        # 添加模型结果
        for key, val in data.items():
            if key != "Original_Row_Data":
                row_dict[key] = val

        final_data.append(row_dict)

    df_out = pd.DataFrame(final_data)

    # 确保输出目录存在
    if not os.path.exists(OUT_DIR):
        os.makedirs(OUT_DIR)

    out_path = os.path.join(OUT_DIR, OUT_FILE_NAME)
    df_out.to_excel(out_path, index=False)

    print(f"\n完成！结果已保存至: {out_path}")
    print("请打开Excel查看 Output 列是否有效区分了 'GPT/LLM' 和 '传统NLP'。")


if __name__ == "__main__":
    main()
