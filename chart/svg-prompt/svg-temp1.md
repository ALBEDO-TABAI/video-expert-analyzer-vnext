## SVG NARRATIVE STRUCTURE DIAGRAM — AGENT PROMPT

### 任务描述

根据你完成的叙事分析报告，生成一张画面线 / 叙事主题 / 语言线
三栏对照的 SVG 结构图。

---

### 图表规格

- 格式：SVG，viewBox="0 0 680 [动态高度]"
- 宽度：width="100%"，不得写死像素值
- 无外层容器 div，直接输出 <svg> 元素
- 背景：透明（不设任何背景色）
- 必须包含 role="img"、<title> 和 <desc> 无障碍标签

---

### 结构规则

**整体布局：三栏 + 行标题行**
[行标题行]  画面线  |  叙事弧线（主题）  |  语言线
[分隔线]
[第 1 幕行]  左卡片  ←→  中卡片  ←→  右卡片
[第 2 幕行]  左卡片  ←→  中卡片  ←→  右卡片
...
[第 N 幕行]  左卡片  ←→  中卡片  ←→  右卡片

**坐标系**
- 安全区：x=40 到 x=640，y=40 到 y=(viewBox高度-20)
- 三列 x 起点：左列 x=40，中列 x=256，右列 x=472
- 每列卡片宽度：168px
- 列间连接箭头区域：x=208→254（左到中），x=424→470（中到右）

**行间距计算**
- 标题行高度：约 35px（含分隔线）
- 每幕行高度：56px（卡片高）+ 22px（行间距）= 78px
- 第 N 幕的卡片 y 起点 = 50 + (N-1) × 90
  （根据实际幕数调整，确保最后一幕底边 + 20px = viewBox 高度）

---

### 卡片规格

每个卡片为双行文字卡片：

```svg
<g class="node c-{COLOR}">
  <rect x="{X}" y="{Y}" width="168" height="56" rx="8" stroke-width="0.5"/>
  <text class="th" x="{X+84}" y="{Y+19}" 
        text-anchor="middle" dominant-baseline="central">
    主标题（≤10字）
  </text>
  <text class="ts" x="{X+84}" y="{Y+39}" 
        text-anchor="middle" dominant-baseline="central">
    副标题（≤16字）
  </text>
</g>
```

卡片点击绑定 sendPrompt，内容为"详细分析 [主标题] 段落"：
```svg
<g class="node c-{COLOR}" onclick="sendPrompt('详细分析 [主标题] 段落')">
```

---

### 颜色分配规则

每一幕分配一个颜色，所有三列卡片使用**同一幕的颜色**。
颜色编码叙事情感阶段，而非视觉装饰，按以下逻辑选色：

| 叙事阶段特征 | 推荐色 |
|---|---|
| 开场建立/张力铺垫 | c-coral |
| 压制/标签/被动处境 | c-pink |
| 对抗/质问/张力高峰 | c-purple |
| 审判/商品化/批判顶点 | c-gray |
| 宣告/主权声索 | c-teal |
| 反转/夺权/收束 | c-green |
| 可根据实际叙事情感灵活调整 | — |

禁止对不同幕使用相同颜色（颜色必须区分各幕）。

---

### 连接箭头规格

**水平箭头**（同行，左→中，中→右）：

```svg
<line x1="208" y1="{卡片中心Y}" x2="254" y2="{卡片中心Y}"
      class="arr" marker-end="url(#arrow)"
      stroke="var(--color-border-secondary)"/>
<line x1="424" y1="{卡片中心Y}" x2="470" y2="{卡片中心Y}"
      class="arr" marker-end="url(#arrow)"
      stroke="var(--color-border-secondary)"/>
```

**垂直箭头**（同列，上幕→下幕，三列各一条）：

```svg
<line x1="{列中心X}" y1="{上幕卡片底边+2}" x2="{列中心X}" y2="{下幕卡片顶边-2}"
      class="arr" marker-end="url(#arrow)"
      stroke="var(--color-border-secondary)"/>
```

三列中心 X 值：左列 124，中列 340，右列 556。

---

### 必须包含的 SVG defs

```svg
<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5"
          markerWidth="6" markerHeight="6" orient="auto-start-reverse">
    <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke"
          stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </marker>
</defs>
```

---

### 标题行规格

```svg
<text class="ts" x="124" y="28" text-anchor="middle"
      style="font-weight:500">画面线</text>
<text class="ts" x="340" y="28" text-anchor="middle"
      style="font-weight:500">叙事弧线（主题）</text>
<text class="ts" x="556" y="28" text-anchor="middle"
      style="font-weight:500">语言线</text>
<line x1="40" y1="35" x2="640" y2="35"
      stroke="var(--color-border-tertiary)" stroke-width="0.5"/>
```

---

### 内容填充规则

根据你的叙事分析，为每一幕填写三张卡片的内容：

**左卡片（画面线）**
- 主标题：该幕的核心空间/场景名称（≤8字）
- 副标题：主导视觉元素或灯光/色调特征（≤14字）

**中卡片（叙事主题）**
- 主标题：该幕的叙事功能/主体状态（≤8字）
- 副标题：时间戳范围，格式 "HH:MM – HH:MM"

**右卡片（语言线）**
- 主标题：该幕的核心歌词/旁白关键词或句（≤16字）
- 副标题：该歌词/旁白的叙事功能一句话描述（≤14字）

---

### viewBox 高度计算公式
幕数 = N
viewBox 高度 = 50 + N × 90 + 20

示例：6幕 → 50 + 6×90 + 20 = 610
示例：4幕 → 50 + 4×90 + 20 = 430

---

### 输出禁忌

- 禁止在 SVG 内部写解释性文字段落
- 禁止使用 <style> 块定义颜色（使用 c-{color} class）
- 禁止硬编码十六进制颜色值
- 禁止在任何 <text> 元素上省略 class 属性
- 禁止让卡片文字超出 168px 宽度（主标题≤10字，副标题≤16字）
- 禁止将两个不同幕设为同一颜色
- 垂直箭头必须三列都画，不可只画中列