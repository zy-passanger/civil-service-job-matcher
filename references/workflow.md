# 运行与官网发现

## 环境与输入

Python 3.9以上。依赖为openpyxl、xlrd、beautifulsoup4、pypdf。优先使用已有运行环境；缺依赖时在本次`work/`建venv并安装`scripts/requirements.txt`，不要修改系统Python或技能目录。

```bash
python3 -m venv "$RUN/venv"
"$RUN/venv/bin/python" -m pip install -r "$SKILL/scripts/requirements.txt"
```

后续用同一Python执行脚本。默认聊天输入；用户喜欢表单时提供`assets/input-form.html`，表单离线导出档案JSON，交给技能后由助手执行联网采集。表单本身不直接访问省考网站，也不保存到外部服务。

## 官网发现与sources.json

读取`discover`生成的任务，调用可用的web/search工具逐省检索。优先官方主管部门、组织部门、人事考试机构及当次公告指定渠道。确认主办机构、官方互链与具体招录范围；搜索摘要、培训网站域名和用户上传文件都不能自动标官方。

新年份必须实际搜索。对于“最新”，检查是否已有更晚年度常规招录，不能简单取今年，也不能被更新日期较新的补录／面试公告带偏。多个省允许解析到不同年份，必须展示。

每条target格式：

```json
{
  "targets": [{
    "province": "湖南",
    "year": 2026,
    "exam_type": "省考公开招录",
    "batch": "regular",
    "coverage_confirmed": false,
    "sources": [{
      "url": "https://www.hxw.gov.cn/content/2026/01/13/14851200.html",
      "kind": "announcement",
      "verified": true,
      "publisher": "中共湖南省委组织部红星网",
      "verification_evidence": "由官方专题链接到此公告，页面主办机构已核对；填写实际核验日期"
    }]
  }]
}
```

此为2026历史结构示例，不是最新批次默认值。`kind`可为announcement、jobs、guide、catalog、revision。可为已发现的直接附件单独增加source；跨站页面须另外核验，直接由官方父页链接的附件保存父页关系。

采集器最多重试2次、同省最多20个HTML页面、深度2；结果的skipped和failures必须检查，不能将有限爬取当作全站覆盖。如果需要更多页面先核对链接，然后追加直接source或合理提高`--max-pages`。单省失败不阻塞其他省。

下载器能处理HTML、XLSX、XLS、CSV、PDF、DOCX、ZIP。旧DOC保留原文，调用环境可用的Word转换工具或官方替代格式提取；PDF文本可提取，表格需助手核对列关系后转JSON/CSV。扫描件或验证码页面明确标待处理；已获取部分继续匹配。

## 覆盖核对

必须对照公告检查：全省表还是仅省直？地市分表是否全？定向／特殊职位是否另有公告？更正、核减和取消是否已纳入？

特别是文件名叫“某省职位表”，仍可能只列省直详细岗位并在尾部汇总地市总数。不能只看文件名或目录中有jobs附件就标全省完成。当前验证中安徽2026官方附件存在这种结构；其他地市需按当次官方指定入口继续获取。

`coverage_confirmed`只能在完成上述覆盖检查后为true。目录缺失或更正尚未检查时仍为partial。下载成功不等于解析成功；返回HTML验证页面也不等于拿到了Excel。

## 标准化与目录

生成目标target.json，固定province/year/batch/exam_type四项。source.json采用采集台账中对应文件记录，保留URL、hash、publisher等。

`normalize_jobs.py`自动识别合并表头、合并值、重复表头、尾注和前导零；检查输出sheets/notes/issues。未识别列可用`--field-map`传原表头到标准字段的映射。不能为了消除REVIEW把未知资格列映射为展示字段。

湖南分层专业目录：

```bash
python3 "$SKILL/scripts/extract_catalog.py" --input "$RUN/catalog.xlsx" --layout hunan --target "$RUN/target.json" --source "$RUN/catalog-source.json" --out "$RUN/catalog.json"
```

具有“专业名称、专业代码、专业类”等列的平表用`--layout flat --level bachelor`等；未知结构由助手读官方文件后转换。研究生目录若明确以研究生为一组，可分别为master和doctorate建立同一来源的映射；不能把本专科目录提升为研究生目录。

其他省不必加载所有专业来完成用户匹配：可抽取用户实际专业对应的正式名称、代码、所有相关类别、新旧对应关系，记录页码／单元格。没有读取完整归属时不得设置catalog_categories_complete；没有确认用户专业已列入适用目录时，不可凭不相似自动判专业FAIL。

## 规则完善与重算

首次运行允许大量REVIEW，它用于找到待解析字段。助手必须继续读取有希望的候选原文，把能从现有官方资料解决的条件转换为表达式，再重算。最后仅保留个人事实未知、来源缺失、政策歧义、目录外认定等实质核验项。

典型任务：把年龄的实际出生日期区间写成date_between；把“党员且男性”写成all_of；把“甲或乙”写成any_of；根据当次政策验证非最高学历和应届限制；工作经历按政策起止计算并去除重叠，把已核实月数绑定profile_hash。未写到日的年龄或期限不能擅自补日。

修订同职位时先由助手建立生效版本、更新原文及证据，旧数据单独归档。程序发现同UID有不同条件会保留冲突提示，不擅自按文件下载顺序选版本。

输出到用户时引用具体官方页面／附件。当前可报清单只放报名中、范围内、用户接受且来源核验的职位；报名未开始、已截止、未知及取消另列。只有学历专业输入时完整资格通常为B，这是资料缺口，不是“没有合适岗位”。
