#!/usr/bin/env python3
from __future__ import annotations

VISUAL_AXIS_LABELS = {"R": "原创现实拍摄", "P": "原创演绎拍摄", "S": "二创素材", "D": "设计 / 动态图形", "H": "混合型"}
AUDIO_AXIS_LABELS = {"L": "语言主导", "M": "音乐主导", "E": "音效 / 梗音主导", "LM": "语言 + 音乐并重", "N": "听觉弱参与"}

ROUTE_FRAMEWORKS = {
    ("P", "LM"): ("narrative_performance", "叙事型表演内容", "叙事短片 / 剧情广告 / 剧情化 MV"),
    ("S", "M"): ("mix_music", "音乐节奏向二创", "游戏 / 影视混剪（音乐节奏向）"),
    ("P", "E"): ("meme", "抽象搞笑 / 梗视频", "抽象搞笑视频 / 无厘头段子"),
    ("S", "E"): ("meme", "抽象搞笑 / 梗二创", "鬼畜 / 梗视频 / 表情包式二创"),
    ("R", "M"): ("cinematic_life", "生活电影化剪辑", "生活电影化剪辑 / 氛围 Vlog"),
    ("S", "L"): ("commentary_mix", "评论向素材二创", "影视 / 游戏解说、评论向混剪"),
    ("D", "M"): ("concept_mv", "概念 MV / 情绪渲染型", "动态设计视频 / 概念 MV"),
    ("P", "M"): ("concept_mv", "概念 MV / 情绪渲染型", "情绪型广告 / 品牌宣传片 / 无对白 MV"),
    ("R", "L"): ("documentary_generic", "纪实 / 讲述型内容", "纪录 / 纪实 / 教程 / 访谈"),
    ("R", "LM"): ("documentary_generic", "生活记录型内容", "普通 Vlog / 生活记录"),
    ("R", "E"): ("reality_sfx", "现实音效实验", "街头恶搞 / 实验音效片"),
    ("R", "N"): ("silent_reality", "弱听觉现实记录", "纯画面纪实 / 环境观察"),
    ("P", "N"): ("silent_performance", "默片风格表演", "无声表演 / 哑剧 / 舞蹈"),
    ("S", "N"): ("pure_visual_mix", "纯视觉混剪", "无声混剪 / 画面蒙太奇"),
    ("D", "L"): ("infographic_animation", "信息图动画", "数据可视化 / 教学动画"),
    ("D", "E"): ("abstract_sfx", "抽象音效设计", "实验动画 / 音效艺术"),
    ("D", "N"): ("pure_motion_graphics", "纯视觉动态图形", "无声MG动画"),
    ("D", "LM"): ("narrative_motion_graphics", "叙事型动态图形", "故事化MG / 解释性动画"),
    ("H", "L"): ("hybrid_commentary", "混合型评论内容", "多素材类型评论"),
    ("H", "M"): ("hybrid_music", "混合型音乐内容", "多风格音乐视频"),
    ("H", "E"): ("hybrid_meme", "混合型梗内容", "跨类型搞笑"),
    ("H", "LM"): ("hybrid_narrative", "混合型叙事", "多手法叙事内容"),
    ("H", "N"): ("hybrid_ambient", "混合型氛围", "实验性氛围片"),
    ("S", "LM"): ("narrative_mix", "叙事型混剪", "故事化素材重组"),
    ("P", "L"): ("lecture_performance", "讲述型表演", "演讲 / 脱口秀 / 教学表演"),
}

LANGUAGE_LED_FRAMEWORKS = {
    "technical_explainer",
    "documentary_generic",
    "commentary_mix",
    "lecture_performance",
    "hybrid_commentary",
    "infographic_animation",
    "narrative_motion_graphics",
}

ATMOSPHERIC_FRAMEWORKS = {
    "mix_music",
    "concept_mv",
    "cinematic_life",
    "hybrid_music",
    "hybrid_ambient",
    "pure_visual_mix",
    "silent_reality",
    "silent_performance",
    "narrative_mix",
}

MEME_FRAMEWORKS = {
    "meme",
    "hybrid_meme",
    "reality_sfx",
    "abstract_sfx",
}

GRAPHIC_FRAMEWORKS = {
    "pure_motion_graphics",
    "infographic_animation",
    "narrative_motion_graphics",
}

EXPLANATORY_PATTERNS = (
    r"\bhow to\b",
    r"\bhow does\b",
    r"\bwhy does\b",
    r"\bwhat is\b",
    r"\bexplained?\b",
    r"\bbreakdown\b",
    r"\bstep by step\b",
    r"\btutorial\b",
    r"\bguide\b",
    r"\bwalk(?:ing)? through\b",
    r"\bprocess\b",
    r"\bworkflow\b",
    r"\bmechanism\b",
    r"\bprinciple\b",
    r"怎么",
    r"如何",
    r"为什么",
    r"原理",
    r"教程",
    r"讲解",
    r"拆解",
    r"步骤",
    r"评测",
    r"详解",
    r"科普",
)

MUSIC_INTENT_PATTERNS = (
    "mv",
    "official mv",
    "music video",
    "official music video",
    "official video",
    "lyric video",
    "performance video",
    "music film",
    "ost",
    "soundtrack",
    "音乐",
    "音樂",
    "歌曲",
    "专辑",
    "配乐",
    "電子樂",
    "电子乐",
    "bgm",
    "remix",
    "beat",
    "节奏",
    "節奏",
)

COMMENTARY_TITLE_KEYWORDS = (
    "影评",
    "影評",
    "评论",
    "評論",
    "解析",
    "解说",
    "解說",
    "讲解",
    "講解",
    "解读",
    "解讀",
    "分析",
    "review",
    "reaction",
    "breakdown",
    "explained",
)

COMMENTARY_VISUAL_KEYWORDS = (
    "字幕卡",
    "画面对照",
    "畫面對照",
    "镜头对照",
    "鏡頭對照",
    "证据",
    "證據",
    "原片片段",
    "素材拼接",
    "解说字幕",
    "解說字幕",
    "旁白分析",
)

TRAILER_TITLE_PATTERNS = (
    r"\bofficial trailer\b",
    r"\btrailer\b",
    r"\bteaser\b",
    r"\btv spot\b",
    r"\bpreview\b",
    r"预告",
    r"先导",
    r"终极预告",
)

RELEASE_TEXT_PATTERNS = (
    r"\bonly in theaters\b",
    r"\bin theaters\b",
    r"\bcoming soon\b",
    r"\bcoming this\b",
    r"\bthis may\b",
    r"\bthis summer\b",
    r"\bthis fall\b",
    r"\bteaser\b",
    r"\btrailer\b",
    r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b",
    r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b",
    r"上映",
    r"院线",
    r"档期",
    r"预告",
)

QUESTION_PATTERNS = ("为什么", "怎么", "怎麼", "如何", r"\?", "？", "What", "How", "Why")
STEP_PATTERNS = ("首先", "然后", "接着", "所以", "因为", "需要", "负责", "结果", "原来", "说明", "就是", "第一", "第二", "第三")
RECAP_PATTERNS = ("最后", "總", "总", "总结", "结论", "因此", "这就是", "完成", "最快")
OVERVIEW_KEYWORDS = ("大全景", "全景", "俯看", "顶视", "围住", "整体", "总览", "整套", "站位", "框架", "结构", "图示")
DETAIL_KEYWORDS = ("特写", "近景", "轮胎", "枪", "千斤顶", "手", "细节", "局部", "轮毂", "按钮", "图标")

TECH_OPENING_RATIO = 0.12
TECH_EARLY_RATIO = 0.35
TECH_MIDDLE_START_RATIO = 0.2
TECH_MIDDLE_END_RATIO = 0.75
TECH_LATE_START_RATIO = 0.65
GENERAL_OPENING_RATIO = 0.15
GENERAL_EARLY_RATIO = 0.35
GENERAL_LATE_START_RATIO = 0.7
GENERAL_CLOSING_START_RATIO = 0.75

VISUAL_MIX_MIN_SCORE = 2.0
VISUAL_MIX_DELTA = 1.5
VISUAL_LOW_CONFIDENCE = 0.5
AUDIO_FORCE_WEAK_RATIO = 0.05
AUDIO_WEAK_PARTICIPATION_RATIO = 0.15
AUDIO_LM_VOICEOVER_RATIO = 0.25
AUDIO_LM_DIALOGUE_RATIO = 0.3
AUDIO_AXIS_TIE_DELTA = 1.2

# Centralized routing heuristics so tuning does not require chasing literals
# across the route/profile functions.
HIGH_IMPACT_SCORE = 8.0
HIGH_FUN_SCORE = 8.0
HIGH_CREDIBILITY_SCORE = 8.0
HIGH_WEIGHTED_SCORE = 8.5
PROFILE_VOICEOVER_HIGH_RATIO = 0.6
PROFILE_VOICEOVER_MEDIUM_RATIO = 0.5
PROFILE_VOICEOVER_LOW_RATIO = 0.4
PROFILE_TECHNICAL_MIN_SCORE = 3.0
PROFILE_PROMO_MAX_SCORE = 2.0
PROFILE_NARRATIVE_MIN_SCORE = 4.0
PROFILE_TRAILER_PROMO_MIN_SCORE = 2.0
PROFILE_TECHNICAL_MARGIN = 0.5
PROFILE_DIALOGUE_UPPER_BOUND = 6.0
GRAPHIC_INTENT_MIN_HITS = 2

TECHNICAL_TITLE_SIGNAL_BONUS = 3.0
TECHNICAL_EXPLANATORY_HIT_MIN = 3
TECHNICAL_EXPLANATORY_SIGNAL_BONUS = 2.0
TECHNICAL_EXPLANATORY_LINE_RATIO = 0.35
TECHNICAL_EXPLANATORY_LINE_BONUS = 2.0
TECHNICAL_DIALOGUE_LIGHT_RATIO = 0.2
TECHNICAL_DIALOGUE_LIGHT_BONUS = 0.5
NARRATIVE_AUTHORED_RATIO = 0.55
NARRATIVE_AUTHORED_BONUS = 2.5
NARRATIVE_SCENE_RATIO = 0.35
NARRATIVE_SCENE_BONUS = 2.0
NARRATIVE_DIALOGUE_RATIO = 0.35
NARRATIVE_DIALOGUE_BONUS = 1.5
NARRATIVE_NONVOICE_RATIO = 0.15
NARRATIVE_NONVOICE_BONUS = 1.0
PROMO_TITLE_SIGNAL_BONUS = 3.0
PROMO_CARD_SIGNAL_BONUS = 2.0
PROMO_RELEASE_SIGNAL_BONUS = 2.0
PROMO_COMMERCIAL_SIGNAL_BONUS = 1.0

VISUAL_TITLE_KEYWORD_WEIGHT = 1.6
VISUAL_SCENE_KEYWORD_WEIGHT = 0.8
VISUAL_AUTHORED_WEIGHT = 2.0
VISUAL_NARRATIVE_WEIGHT = 1.4
VISUAL_COMMERCIAL_WEIGHT = 0.8
VISUAL_ATMOSPHERE_P_WEIGHT = 1.2
VISUAL_ATMOSPHERE_R_WEIGHT = 0.6
VISUAL_INFORMATION_WEIGHT = 1.2
VISUAL_MOVEMENT_WEIGHT = 1.0
VISUAL_WIDE_SHOT_WEIGHT = 0.8
VISUAL_ACTION_KEYWORD_WEIGHT = 0.8
VISUAL_STYLE_CONSISTENCY_P_WEIGHT = 0.6
VISUAL_STYLE_CONSISTENCY_D_WEIGHT = 0.4
VISUAL_COLOR_GRADING_WEIGHT = 0.5
VISUAL_TRAILER_PROFILE_WEIGHT = 2.0
VISUAL_TECHNICAL_PROFILE_WEIGHT = 1.5

AUDIO_MUSIC_TITLE_WEIGHT = 4.0
AUDIO_LM_MUSIC_TITLE_WEIGHT = 3.0
AUDIO_MEME_TITLE_WEIGHT = 5.0
AUDIO_LANGUAGE_TITLE_WEIGHT = 4.0
AUDIO_MUSIC_FUNCTION_WEIGHT = 2.0
AUDIO_LM_MUSIC_FUNCTION_WEIGHT = 1.5
AUDIO_INFORMATION_FUNCTION_WEIGHT = 2.5
AUDIO_NARRATIVE_FUNCTION_WEIGHT = 1.5
AUDIO_LM_NARRATIVE_FUNCTION_WEIGHT = 1.0
AUDIO_VOICEOVER_RATIO_WEIGHT = 5.0
AUDIO_LM_BALANCED_VOICEOVER_WEIGHT = 4.0
AUDIO_WEAK_AUDIO_WEIGHT = 4.0
AUDIO_LOW_VOICEOVER_MUSIC_WEIGHT = 2.0
AUDIO_COUNTERPOINT_M_WEIGHT = 1.0
AUDIO_COUNTERPOINT_LM_WEIGHT = 0.8
AUDIO_COMPLEMENTARY_L_WEIGHT = 1.0
AUDIO_TRAILER_LM_WEIGHT = 2.5
AUDIO_TRAILER_BALANCED_VOICEOVER_WEIGHT = 1.5
AUDIO_TRAILER_NONVOICE_M_WEIGHT = 1.0
AUDIO_TRAILER_NONVOICE_LM_WEIGHT = 1.5
AUDIO_TECHNICAL_LANGUAGE_WEIGHT = 2.5
AUDIO_MUSIC_DIALOGUE_WEIGHT = 2.0

