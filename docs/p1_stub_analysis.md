# P1 Stub Template Analysis — 7 个 Stub 模板升级价值评估

> 生成时间：2024-XX
> 分析依据：`audiovisual_route_engine.py` 路由表 + `audiovisual_template_engine.py` context builder + 各 family 模板内容

---

## 总览

当前 7 个 stub 模板仅包含 `<!-- INCLUDE:_family_xxx.md -->` 一行，完全复用家族模板。本文逐一评估它们是否值得升级为独立模板。

---

## 1. `template_abstract_sfx.md` → `_family_meme.md`

| 维度 | 分析 |
|------|------|
| **路由组合** | D（设计/动态图形）+ E（音效/梗音主导） |
| **路由名称** | `abstract_sfx` — "抽象音效设计" |
| **典型内容** | 实验动画、音效艺术、声音可视化、Generative Art + 声音同步 |
| **家族差异** | `_family_meme` 围绕"笑点、反差、音画时机"设计分析框架。但 abstract_sfx 的核心不是搞笑，而是**声音与抽象视觉的同步规则**——它更接近节奏/形式美学分析，而非娱乐密度分析 |
| **Python 端区分** | `_build_meme_family_context()` 已为 `abstract_sfx` 配置独立的 `route_template_focus`（"声音和抽象视觉之间，是不是反复遵守同一套变化规则"）、`route_metric_note`（`_abstract_sfx_sync_analysis`）和 `route_risk_note`（`_abstract_sfx_failure_risk`），表明开发者已意识到其独特性 |
| **结论** | **YES — 建议升级** |
| **理由** | 当前 meme 家族的 TASKS 段全部围绕"笑点或反差组织"撰写，而 abstract_sfx 的观众期待是同步精度和形式美感。TASKS 段需要替换为"声画同步规则""变化一致性""形式美感维持"等分析维度。DATA 段也应增加 `avg_aesthetic` |

---

## 2. `template_hybrid_meme.md` → `_family_meme.md`

| 维度 | 分析 |
|------|------|
| **路由组合** | H（混合型）+ E（音效/梗音主导） |
| **路由名称** | `hybrid_meme` — "混合型梗内容" |
| **典型内容** | 跨类型搞笑视频（混合实拍+二创+设计素材的搞笑内容） |
| **家族差异** | 与 `meme`（P+E）的核心区别是**素材来源多元**——需要判断"多种梗法叠加后是互相加码还是互相抢戏"。但分析框架（笑点密度、反差、同步率）完全一致 |
| **Python 端区分** | 已有独立的 `route_template_focus`（"多种梗法叠在一起时，是互相加码，还是互相抢戏"）和独立的 `_hybrid_meme_mix_analysis` / `_hybrid_meme_viewing_advice` / `_hybrid_meme_failure_risk` |
| **结论** | **NO — 不需要升级** |
| **理由** | 分析框架与 meme 高度一致，差异点已通过 `route_template_focus` 和 route-specific notes 充分覆盖。独立模板的额外收益不大 |

---

## 3. `template_hybrid_narrative.md` → `_family_narrative.md`

| 维度 | 分析 |
|------|------|
| **路由组合** | H（混合型）+ LM（语言+音乐并重） |
| **路由名称** | `hybrid_narrative` — "混合型叙事" |
| **典型内容** | 多手法叙事视频（纪实+表演+设计混合推进同一条叙事线） |
| **家族差异** | 与 `narrative_performance`（P+LM）的核心区别是**手法来源多元**——需要判断多手法混合是否让主线更清楚。但叙事推进的"开场→中段→高点→收束"分析框架完全适用 |
| **Python 端区分** | 已有独立 `route_template_focus`（"多手法混合之后，主叙事有没有更清楚"）和 `_hybrid_narrative_layering_analysis` / `_hybrid_narrative_failure_risk` |
| **结论** | **NO — 不需要升级** |
| **理由** | 叙事家族框架已足够泛化，加上 route-specific notes 的区分，覆盖充分。多手法的"加法还是减法"判断已通过 focus 和 notes 传达 |

---

## 4. `template_meme.md` → `_family_meme.md`

| 维度 | 分析 |
|------|------|
| **路由组合** | P（原创演绎拍摄）+ E（音效/梗音主导）或 S（二创素材）+ E |
| **路由名称** | `meme` — "抽象搞笑/梗视频" |
| **典型内容** | 抽象搞笑视频、无厘头段子、鬼畜、梗视频、表情包式二创 |
| **家族差异** | `meme` 就是 meme 家族的**原型路由**——家族模板本身就是为它设计的 |
| **Python 端区分** | `_build_meme_family_context()` 以 `meme` 作为默认分支 |
| **结论** | **NO — 不需要升级** |
| **理由** | `_family_meme.md` 的分析框架就是为 `meme` 路由量身打造的，完全匹配。stub 是最正确的选择 |

---

## 5. `template_narrative_motion_graphics.md` → `_family_graphic.md`

| 维度 | 分析 |
|------|------|
| **路由组合** | D（设计/动态图形）+ LM（语言+音乐并重） |
| **路由名称** | `narrative_motion_graphics` — "叙事型动态图形" |
| **典型内容** | 故事化 MG 动画、解释性动画（有完整叙事弧线的动态图形内容） |
| **家族差异** | `_family_graphic.md` 围绕"结构清晰度""运动与节奏"设计框架。但 narrative_motion_graphics 的核心不只是结构清不清楚，而是**图形是否在推进叙事**——它同时属于 LANGUAGE_LED_FRAMEWORKS，Python 端也调用 `_narrative_motion_graphics_story_role` 和 `_narrative_motion_graphics_integrity` |
| **Python 端区分** | 已有独立的 story_role / integrity / failure_risk 三个 builder 函数 |
| **结论** | **YES — 建议升级** |
| **理由** | 这个路由的核心判断维度是"图形对叙事的推进作用"，需要在 TASKS 段增加"叙事推进"相关的分析维度（开场设定→中段推进→高点→收束），同时保留图形的结构和运动分析。当前 graphic 家族的纯"结构清晰度"框架对它来说维度不够 |

---

## 6. `template_pure_motion_graphics.md` → `_family_graphic.md`

| 维度 | 分析 |
|------|------|
| **路由组合** | D（设计/动态图形）+ N（听觉弱参与）或 D + M（音乐主导） |
| **路由名称** | `pure_motion_graphics` — "纯视觉动态图形" |
| **典型内容** | 无声 MG 动画、纯视觉动效展示 |
| **家族差异** | `_family_graphic.md` 已为其提供合适的"结构→细节→运动"框架。纯视觉动态图形是 graphic 家族的**核心成员之一** |
| **Python 端区分** | 已有独立的 `_motion_graphics_flow_analysis` / `_motion_graphics_failure_risk`，focus 也有独立配置（"纯视觉的运动和转场，能不能独立撑住观看连续性"） |
| **结论** | **NO — 不需要升级** |
| **理由** | graphic 家族框架完全匹配。无声意味着不需要额外的语言维度，结构+运动+节奏的分析已足够覆盖。route-specific notes 足以区分 |

---

## 7. `template_reality_sfx.md` → `_family_meme.md`

| 维度 | 分析 |
|------|------|
| **路由组合** | R（原创现实拍摄）+ E（音效/梗音主导） |
| **路由名称** | `reality_sfx` — "现实音效实验" |
| **典型内容** | 街头恶搞、实验音效片（在现实场景中用夸张音效重新解释动作） |
| **家族差异** | 与标准 meme 的区别在于**现实基底**——不是靠剧本搞笑，而是靠音效对现实动作的"扭曲解释"。分析应关注"音效介入前后观众对同一动作的理解差"，而不只是笑点密度 |
| **Python 端区分** | 已有独立的 `_reality_sfx_distortion_analysis` / `_reality_sfx_viewing_advice` / `_reality_sfx_failure_risk` |
| **结论** | **NO — 暂不升级**（但优先级高于 hybrid_meme 和 meme） |
| **理由** | 虽然"现实扭曲"的分析视角与纯梗视频不同，但核心指标（反差、同步、密度）仍然一致。Python 端的 route-specific notes 已较好地覆盖了差异。如果后续 meme 家族做更精细的拆分，reality_sfx 应是第一个被升级的候选 |

---

## 升级优先级排序

| 优先级 | Stub | 建议 | 核心理由 |
|:------:|------|:----:|----------|
| **P0** | `template_abstract_sfx.md` | **升级** | 分析框架与 meme 家族严重不匹配——不是搞笑内容，是形式/同步美学 |
| **P0** | `template_narrative_motion_graphics.md` | **升级** | 需要"图形推进叙事"的复合分析维度，graphic 家族的纯结构框架不够 |
| P2 | `template_reality_sfx.md` | 观望 | 有独特的"现实扭曲"视角，但当前 route notes 够用 |
| P3 | `template_hybrid_meme.md` | 保持 | route notes 已充分覆盖差异 |
| P3 | `template_hybrid_narrative.md` | 保持 | 叙事框架足够泛化 |
| P3 | `template_meme.md` | 保持 | 家族原型，完美匹配 |
| P3 | `template_pure_motion_graphics.md` | 保持 | graphic 家族核心成员，完美匹配 |

---

## 附录：家族-路由映射表（来自 `audiovisual_route_engine.py`）

```
MEME_FRAMEWORKS     = { meme, hybrid_meme, reality_sfx, abstract_sfx }
GRAPHIC_FRAMEWORKS  = { pure_motion_graphics, infographic_animation, narrative_motion_graphics }
ATMOSPHERIC_FRAMEWORKS = { mix_music, concept_mv, cinematic_life, hybrid_music, hybrid_ambient, pure_visual_mix, silent_reality, silent_performance, narrative_mix }
LANGUAGE_LED_FRAMEWORKS = { technical_explainer, documentary_generic, commentary_mix, lecture_performance, hybrid_commentary, infographic_animation, narrative_motion_graphics }
```

> 注意：`infographic_animation` 和 `narrative_motion_graphics` 同时属于 GRAPHIC 和 LANGUAGE_LED 两个家族集合，但实际使用 `_build_graphic_family_context` 作为 builder。
