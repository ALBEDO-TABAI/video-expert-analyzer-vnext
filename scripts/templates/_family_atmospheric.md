<!-- SYSTEM -->
<!-- INCLUDE:_base_system.md -->

你将收到一条 **{{route_label}}{{route_subtype_str}}** 视频的分镜表数据和计算摘要。
重点不是看它有没有讲明白所有事件，而是看它有没有把画面、节奏和情绪真正拧成同一股感觉。
这条路由当前的核心判断重点是：{{route_template_focus}}
<!-- /SYSTEM -->

<!-- DATA -->
## 路由判断（已由系统确认，直接输出，不需重写）

- 路由结果：{{route_label}}{{route_subtype_str}}
- 总场景数：{{total_scenes}}
- 平均加权分：{{weighted_avg}}/10
- 可用素材占比：{{usable_ratio}}%

---

## 数据摘要（仅供分析参考，不直接粘贴进报告）

**场景总览**
- 平均美学分：{{avg_aesthetic}}/10
- 平均冲击力：{{avg_impact}}/10
- 平均记忆度：{{avg_memorability}}/10

**氛围组织**
- 风格一致性评分：{{style_consistency}}/10
- 气氛开场场景：{{atmosphere_opening_refs}}
- 意象锚点场景：{{motif_scene_refs}}
- 节奏抬升场景：{{rhythm_scene_refs}}
- 情绪高点场景：{{crest_scene_refs}}
- 收口余味场景：{{closing_scene_refs}}

**情绪结构**
- 情绪曲线波动幅度：{{emotion_variance}}
- 情绪峰值场景数：{{emotion_peak_count}}
- 情绪峰值场景：{{emotion_peak_scene_refs}}

**路由补充判断**
- 关键说明：{{route_metric_note}}
- 补充观察：{{route_support_note}}
- 主要风险：{{route_risk_note}}

**视听对齐数据**
- 对齐度：{{alignment_level}}
- 画面高点场景：{{visual_peak_scenes}}
- 语言高点场景：{{language_peak_scenes}}

**高光场景（系统已选，报告中优先引用）**
{{highlight_specs_list}}

**代表场景（按分析维度分组）**
{{scenes_by_dimension}}
<!-- /DATA -->

<!-- TASKS -->
请基于上方数据，写出以下所有节的完整内容。
严格使用节名，按顺序输出，不跳过任何节。

---

<!-- INCLUDE:_base_content_synopsis.md -->

---

## 先看结论

用 2-4 句话说清楚这条片子的核心感觉和成立方式。需要回答：
- 它最主要靠什么把观众带进去？
- 它的高点是慢慢养出来的，还是突然顶起来的？
- 它最大的优点和最大的风险分别是什么？

<!-- FIGURE:opening -->

---

## 氛围与节奏组织

围绕气氛开场、意象锚点、节奏抬升和高点场景，判断这条片是不是一直在推同一股感觉。3-5 句。

需要回答：
1. 它的风格和情绪是不是一直在同一个方向上？
2. 哪几个 Scene 最能证明它成立？
3. 它是靠意象、靠节奏，还是靠空间和动作把整条片托住的？

<!-- FIGURE:atmosphere_peak -->

---

## 高点与失效风险

结合情绪曲线、补充观察和风险说明，判断它最容易在哪掉线。2-4 句。

需要回答：
1. 先看哪几段最能判断它成不成立？给具体 Scene 编号。
2. 它最容易在哪种情况下失效？
3. 如果只能改一件事，最该改什么？

---

## 综合述评

按以下格式输出：
- 类型定性：[一句话说明这条片的表达类型，比路由名更具体]
- 目标受众：[谁会愿意为这种感觉停下来]
- 核心意图：[这条片最想让观众感受到什么]

用 2-3 句说清楚这股感觉立没立住。它是从头到尾一个方向推过去的，还是中途散掉了？点出最能代表这条片气质的一个场景，再说一件如果改了会明显不同的事。

<!-- INCLUDE:_base_alignment.md -->
<!-- INCLUDE:_base_scoring_table.md -->
<!-- /TASKS -->
