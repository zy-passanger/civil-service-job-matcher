---
name: civil-service-job-matcher
description: 根据多个学历、多个专业、培养方式和目标省份，主动查找各省官方公务员招录公告、职位表与专业目录，逐条学历专业匹配并输出主攻、待核验、备选、排除清单。用于省考选岗、多学历报考资格检查和岗位重筛，也支持上传官方职位表。
---

# 公考岗位自动匹配助手

默认完成从输入到官方资料获取、资格匹配和结果文件的整个流程。用户只给学历专业和省份时立即采集公开资料，不要求先上传职位表；其他资格信息按候选条件补齐。

## 输入

接受聊天文本、JSON或本技能的 [动态输入表单](assets/input-form.html)。最小格式：

```text
省份：湖南、安徽
学历专业：
- 大专—物流管理（全日制）
- 本科—计算机科学与技术（自考）
- 本科—会计学、法学（全日制）
- 硕士研究生—软件工程（非全日制）
年度：最新已发布
```

这是格式示例，不是用户事实。学历可重复添加；多个专业需各自保留证书和主修／辅修／第二学位性质。培养方式不清楚保留未知，不自行补成全日制。自考、全日制、统招、学历和学位分别记录。仅有硕士学位不等于研究生学历。

有多义或自然语言输入时由助手整理JSON，保留原文和歧义；脚本解析器只处理上述固定行格式。不反复确认已经明确的内容。完整字段与表达式见 [数据契约](references/data-contracts.md)。

## 必须维持的判定规则

- 每个合法路径绑定一个学历ID、一个专业ID及对应学位。禁止本科学历与专科专业拼接；一个路径失败不排除其他路径。
- 三态：`PASS`满足、`FAIL`明确不满足、`REVIEW`信息或规则待核验。AND失败优先，OR通过优先。学历或专业列表未确认完整时，已填路径全部失败不能证明全部路径失败。
- 以当省、当年、当批次公告及采用的目录为准。不能按相似词推断专业类别，不跨省借目录。不限专业不自动降低等级。
- 只提供学历专业时先做初筛，年龄、学位、身份等缺失必须保留。未来拿证假设与当前资格分别运行。
- 空白不等于不限。“不限全日制”不能被“全日制”关键词误杀。明确不满足硬条件不能靠推荐分抵消。
- 每个判断保留原文、来源、sheet／行／列或条款。复杂备注由助手读原文并转换为可解释条件；不能只用脚本的REVIEW作为停止工作的理由。
- 资格与偏好、报名时间、官方／测试、当前／历史分别呈现。A主攻和C备选均须资格匹配；B待核验；D有明确失败依据。

## 执行流程

工作文件放在当前项目 `work/civil-service/<run>/`，最终报告放在当前项目允许的outputs目录。绝不将个人档案写入已安装技能目录。

1. 读 [运行流程](references/workflow.md)，确认Python依赖，规范化输入。省份支持大陆省、自治区、直辖市；无年份时逐省查最新已发布常规招录，补录单独处理，展示实际年份。
2. 生成分省检索任务后，**由当前助手实际调用联网搜索／网页读取**查找并核验官方公告、专题及地市入口。`discover`生成的是内部任务清单，不是用户交付；不能停在搜索计划。历史来源登记仅作入口线索。
3. 将验证后的链接写入`sources.json`，运行采集器自动下载官方附件和相关页面。核对地市覆盖、更正和招录人数；访问失败按省分别记录。动态下载或采集器遗漏的附件，用网页工具发现实际链接后继续补采。
4. 运行职位标准化，检查每个sheet的字段映射、表注和行数。读取规则材料及目录，为各省批次生成`policy.json`。湖南分层目录可用目录提取器；其他格式按正式目录生成带原文定位的候选专业映射。不把所有省份的政策强行压成一套。
5. 首次匹配用于定位候选和未解析条件。对与用户学历专业有交集的候选，继续解读相关公告／备注，通过`field_rules`或`policy`表达式补充规则，重算。真实用户事实缺失或必须由招录单位认定的事项才留在核验清单。
6. 输出Markdown报告、Excel、CSV和JSON；指出实际使用学历与专业、官方原文、关键核验问题、分省资料覆盖及报名状态。没有完整覆盖不能声称全省无岗。不能把本技能创建时的测试画像当作用户档案。

## 可执行组件

以下`SKILL`表示本SKILL.md所在目录，`RUN`表示本次工作目录；命令路径均需按实际绝对路径展开。

```bash
python3 "$SKILL/scripts/civil_service.py" profile --input "$RUN/input.txt" --out "$RUN/profile.json"
python3 "$SKILL/scripts/civil_service.py" discover --profile "$RUN/profile.json" --out "$RUN/discovery.json"
# 助手执行联网发现并写好sources.json后，继续：
python3 "$SKILL/scripts/collect_official_sources.py" --sources "$RUN/sources.json" --out "$RUN/raw"
python3 "$SKILL/scripts/normalize_jobs.py" --input "$RUN/positions.xlsx" --target "$RUN/target.json" --source "$RUN/source.json" --out "$RUN/jobs.json"
python3 "$SKILL/scripts/match_jobs.py" --profile "$RUN/profile.json" --jobs "$RUN/jobs.json" --policies "$RUN/policy.json" --collection "$RUN/raw/collection.json" --out "$RUN/report"
```

可一次传多个`--jobs`和`--policies`文件。参数详见各脚本`--help`。`references/official-source-registry.json`含所有可输入省份及已核验历史入口；这不表示每省已预置当年政策。脚本不自带任意省份的黑箱政策库，由当前助手在每次运行中读取官方资料后生成可审计配置。

需要修改或验证程序时运行`scripts/test_matcher.py`。固定脚本无法处理的页面、PDF表格或复杂条件由助手继续完成提取和结构化；保留证据后接回同一匹配流程。
