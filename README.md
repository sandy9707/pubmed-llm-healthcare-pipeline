# PubMed LLM医疗文献筛选与信息提取流水线

本项目是一套完整的自动化处理流水线，用于从 PubMed 检索结果中筛选出"大语言模型（LLM）/生成式AI/智能体（Agent）在医疗领域应用"的文献，并对纳入文献进行结构化信息提取。

## 背景

检索范围为 2022 年 11 月 ChatGPT 发布以来，PubMed 上关于 LLM/GenAI/Agent 在医疗/临床场景应用的全量文献，共约 **20,000+ 篇**。由于 PubMed 单次导出上限为 10,000 条，将检索结果分三段导出。

> 详细检索策略和分段方案见 [`README_检索词.md`](./README_检索词.md)

---

## 流水线概览

```
1_source_pubmed/          PubMed原始 .txt 导出文件
       │
       ▼
[Step 1] 1_parse_pubmed_dir.py     解析 .txt → 合并为 CSV
       │
       ▼
[Step 2o] 2o_extract_cols.py       提取核心4列 → Excel
       │
       ▼
2_extracted_data/          pubmed_summary_4cols.xlsx
       │
       ├──▶ [Step 2] 2_filter_pubmed.py   (可选) 200条小批量验证/Prompt调优
       │                    └─▶ 2_extracted_data/validation_200_results_2models_json.xlsx
       │
       ├──▶ [Step 3] 3_tune_prompt.py     对不一致样本进行二次提示词调优
       │                    └─▶ 3_tuning_results/
       │
       ▼
[Step 4] 4_full_dataset_filter.py  全量筛选（双模型并行，断点续传）
       │
       ▼
4_final_results/          pubmed_summary_4cols_filtered_json.xlsx
       │                  （只保留"非双模型一致拒绝"的文献）
       │
       ▼
[Step 5] 5_extract_data.py         结构化信息提取（10个维度，断点续传）
       │
       ▼
5_final_extraction/        pubmed_extracted_details.xlsx（最终产出）
```

---

## 各脚本说明

### Step 1 — `1_parse_pubmed_dir.py`
将 `1_source_pubmed/` 目录下所有 PubMed 格式 `.txt` 文件解析合并为一张 CSV 表，每行一篇文献，标签（`PMID`、`TI`、`AB` 等）作为列名。多值字段（如多个作者、MeSH词）以分号拼接。

```bash
python3 1_parse_pubmed_dir.py \
    --input-dir 1_source_pubmed \
    --output 1_source_pubmed/pubmed_summary.csv
```

### Step 2o — `2o_extract_cols.py`
从 CSV 中提取 `PMID`、`TI`（标题）、`AB`（摘要）、`DP`（发表日期）四列，去重后保存为 Excel，供后续步骤使用。

```bash
python3 2o_extract_cols.py
```

### Step 2 — `2_filter_pubmed.py`（可选，调试用）
对前 200 条数据进行双模型（qwen2.5:7b + dolphin3:8b）并行筛选，用于验证 Prompt 效果和一致性。结果包含每个模型对每篇文献的判断（是/否/不确定）及一致性标记（Match/Mismatch/Ambiguous）。

```bash
python3 2_filter_pubmed.py
```

### Step 3 — `3_tune_prompt.py`
对 Step 2 / Step 4 中两模型判断不一致（Mismatch）的样本，应用关键词扫描增强版 Prompt 进行二次裁决，辅助提示词迭代优化。

```bash
python3 3_tune_prompt.py
```

### Step 4 — `4_full_dataset_filter.py`
对全量数据集进行双模型并行相关性筛选，大约使用 Ollama API（本地部署，地址 `http://10.9.65.31:11434`）。

**特性：**
- 断点续传：若输出文件已存在则自动加载，跳过已完成条目（`Consistency != Failed/空`）
- 每处理 50 条保存一次中间结果，防止数据丢失
- 14 并发线程，超时 60 秒/请求

```bash
python3 4_full_dataset_filter.py
```

**纳入标准（进入 Step 5 的条件）：** 排除两个模型均明确判定为"否"的文献，其余全部纳入。

### Step 5 — `5_extract_data.py`
对 Step 4 纳入文献提取 **10 个结构化维度**，供系统综述分析使用：

| 字段 | 说明 |
|------|------|
| `tech_category` | 使用技术（LLM / Agent / 其他） |
| `other_tech` | 其他技术的具体内容 |
| `domain_category` | 对应领域（医疗 / 临床 / 其他） |
| `other_domain` | 其他领域的具体内容 |
| `model_names` | 使用的基座模型名称 |
| `problem_solved` | 研究解决的具体问题（一句话总结） |
| `has_secondary_dev` | 是否存在大模型二次开发（是/否/不确定） |
| `secondary_dev_methods` | 二次开发的具体方式（微调/RAG/提示策略等） |
| `is_review` | 是否为综述文章 |
| `research_methodology` | 大模型研究方法类型 |

**特性：**
- 断点续传：加载已有输出文件，跳过两个模型均为 `Status=Done` 的行
- 超时设置 300 秒/请求，每次失败最多重试 3 次
- 14 并发线程，每 50 条写入一次磁盘

```bash
python3 5_extract_data.py
```

---

## 目录结构

```
.
├── 1_source_pubmed/           # PubMed 原始导出 .txt 文件
├── 2_extracted_data/          # 提取的核心列 Excel 及小批量验证结果
├── 3_tuning_results/          # Prompt 调优中间结果
├── 4_final_results/           # Step 4 全量筛选结果
├── 5_final_extraction/        # Step 5 最终结构化提取结果（最终产出）
├── 1_parse_pubmed_dir.py
├── 2o_extract_cols.py
├── 2_filter_pubmed.py
├── 3_tune_prompt.py
├── 4_full_dataset_filter.py
├── 5_extract_data.py
├── extract_200_mismatches.py  # 辅助脚本：提取不一致样本
├── README_检索词.md            # PubMed 检索策略及分段方案
└── README_parse.md            # Step 1 解析脚本说明（英文）
```

---

## 环境依赖

```bash
pip install pandas requests openpyxl
```

运行时需要访问本地 Ollama API 服务（默认地址：`http://10.9.65.31:11434`），并加载以下模型：

- `qwen2.5:7b`
- `dolphin3:8b`

---

## 断点续传说明

**Step 4** 和 **Step 5** 均支持断点续传，可以安全地在中断后重新运行：

- 若输出文件存在，脚本会自动加载已有结果
- 已成功处理的行会被跳过，仅对失败/空白/超时的行重新发起请求
- 无需任何额外操作，直接重新运行即可
