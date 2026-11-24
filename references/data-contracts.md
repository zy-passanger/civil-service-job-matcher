# 档案、职位与规则契约

JSON采用UTF-8。未知用null或unknown，不用false代替未知。空经历／证书列表只有complete=true才代表明确没有。脚本不会自动填写用户政治面貌、毕业／学位日期、应届身份。

## profile.json

核心结构：`target`、`educations[]`、`preferences`、`educations_complete`。

- target：provinces数组；exam_type默认省考公开招录；recruitment_year整数或null；batch为regular/supplementary；mode为current_eligibility/future_scenario。
- as_of_date：本次参考日期，使用用户时区YYYY-MM-DD。报名区间脚本按日比较；最后一天具体时刻由助手依官方时间复核，不能当作整日开放。
- educations：每条id唯一；level为junior_college/bachelor/master/doctorate/other；education_form；full_time；national_unified_admission；recognition_status；graduation_status；graduation_date；majors_complete；majors数组。
- majors：每条id在学历内唯一；name_on_certificate；name_hint；code；role；credential_status；degree。
- role：primary、minor、second_degree、dual_degree、unknown。独立学历应拆记录，不能为了避开审核把辅修改为primary。
- recognition_status与credential_status：verified/self_declared/unknown/rejected，self_declared须来自用户明确陈述。
- graduation_status和degree.status：obtained/pending/not_obtained/unknown，degree另支持not_applicable。degree.level为bachelor/master/doctorate；degree.award_date和expected_award_date独立。
- 一个人拥有多个本科、多专业，不自动意味着每个专业都有学位。
- preferences：cities_ranked、preferred_duties、excluded_regions、accept_township等。脚本提供地区和职责基础排序；其他偏好由助手结合岗位已解析信息筛选，单独记录偏好理由。

未来情景复制profile并标mode=future_scenario，不修改当前档案。政策中的已核实个人推导事实必须绑定本次profile_hash。

## 标准化职位

`normalize_jobs.py`输出target、jobs、sheets、notes、issues和source。

每条job包含job_uid、job_code、target、agency/employer、job_name、duties、count、requirements、locations、raw_fields、source、availability、field_rules。

requirements包含education/major/degree/party/experience/fresh/gender/age/household/other。按层次分列专业时使用major_junior_college/major_bachelor/major_master/major_doctorate。该层次列空白不能假定不限，也不能借另一个层次列。

source最少包括verified、source_type、url、publisher、sha256。synthetic_fixture/third_party/user_supplied_unverified不能进入正式当前岗位统计。可信字段由助手根据实际读取的来源填写，不能因为下载成功就置verified。

无官方职位代码时保留job_code为空，并使用文件hash/sheet/行号生成本次稳定标识；跨修订版本的对齐需人工确认，不能声称该标识是官方职位代码。

availability为open/not_started/closed/cancelled/unknown。未知状态不得放进“当前报名中”清单。招录人数核减和职位取消须应用已核验更正后再导出。

## policy.json

每份政策仅适用一个target四元组。基础结构示例：

```json
{
  "target": {"province": "湖南", "year": 2026, "batch": "regular", "exam_type": "省考公开招录"},
  "reviewed": false,
  "global_rules_complete": false,
  "global_rules": [],
  "path_rules": [],
  "blank_defaults": {},
  "plain_level_mode": {},
  "catalog": [],
  "catalog_categories_complete": false,
  "catalog_name_list_complete": false,
  "registration": {},
  "credential_deadline": null,
  "profile_hash": null,
  "profile_facts": {}
}
```

这不是可以直接通过资格的政策。读完当次通用报考条件，逐条建立global_rules后才设置reviewed和global_rules_complete。最低包含适用的国籍、年龄、不得报考／回避自查、在读／在职等通用条件；尚未发生的体检考察是未来流程事项，不假装已完成。具体是否享受放宽等涉及学历的条件放path_rules。

规则项形式：`{"id":"规则名","expression":{...},"evidence":{"source_url":"真实来源","section":"条款","quote":"必要短原文"}}`。保留必要的短原文即可，不复制整份指南。

表达式支持：

```json
{
  "all_of": [
    {"field": "user.nationality", "op": "eq", "value": "中国"},
    {
      "any_of": [
        {"field": "path.level", "op": "eq", "value": "bachelor"},
        {"field": "path.level", "op": "gte", "value": "master"}
      ]
    }
  ]
}
```

支持all_of、any_of、not；叶子运算eq/in/gte/lte/date_between/on_or_before/contains_any/review。all_of和any_of空数组都为REVIEW。日期要求精确ISO日期，精度不足保留REVIEW。未知运算不会静默通过。

命名空间：user为原profile；path为当前学历加当前专业、degree、major_role等；policy_facts为绑定档案后已核实的推导事实。

`plain_level_mode`将普通的“本科／专科／硕士”等解释为minimum或exact；必须有当次依据。职位表头明确“最低学历要求”可直接按最低层次解释。`blank_defaults`按字段使用`{"value":"不限","evidence":{...}}`，缺证据不生效。

catalog条目：level、name、code、aliases、categories、evidence。类别和代码均来自当次采用目录。设置catalog_categories_complete前确认所收录候选专业的类别列表完整；设置catalog_name_list_complete前确认候选专业确实列在适用目录中，这允许“已经列入目录但不属于要求”判失败。目录外专业仍为REVIEW。

证书截止日与延期例外用graduation_rule/path_rules表达；仅设置统一credential_deadline适合已核对并无例外的路径。用户明确没有学位但可能赶得上截止不能立即判D；确认延期不适用或期限已不可能满足后，用有依据的学位field_rules判定。

工作经历从实际时间段按当次定义排除不计时间、合并重叠后计算。`profile_facts.grassroots_months={"value":24,"evidence":{...}}`；同时设置profile_hash为`common.digest(profile)`。不同档案hash不使用这些推导事实。应届、定向、专业认定等也可用同一机制，但不能写入无来源的“符合=true”。

## 复杂字段的覆盖解释

为job.field_rules中的特定字段添加：

```json
{
  "other": {
    "raw": "中共党员；男性",
    "expression": {
      "all_of": [
        {"field": "user.political_status", "op": "eq", "value": "中共党员"},
        {"field": "user.sex", "op": "eq", "value": "男"}
      ]
    },
    "evidence": {"source_url": "填入实际官方来源", "location": "原始sheet及单元格", "interpretation": "以该职位与当次指南为据"}
  }
}
```

示例不是当年政策，不可直接复制到真实职位。raw必须与requirements中该字段原文完全一致，evidence非空，否则覆盖解释无效。补充的表达式必须涵盖整个原字段，不能只解析“党员”而漏掉证书、户籍、服务承诺等另一条件。遇到明确没有额外限制的原文，可表达为当次可核实事实的条件；不要通过制造恒真字段绕过未解析内容。

## 输出

results.json保留每条学历专业的每项规则；Excel包含全部明细、当前四类、历史及其他状态、逐项依据；Markdown给概要和待核验项；CSV供进一步处理。

不同版本同UID有不同条件会列入conflicting_jobs并要求核验；版本冲突消解后再跑正式结果。报告中FAIL可能来自已明确的不符合条件，不能用“还有未核验项”将其误称可尝试。一个通过路径足以通过学历路径部分，另一失败路径不否决它。
