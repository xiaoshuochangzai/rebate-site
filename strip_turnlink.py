# -*- coding: utf-8 -*-
import re, io

path = r"E:\Jingdong\rebate-site\build_site.py"
with io.open(path, encoding="utf-8") as f:
    text = f.read()

# 1) 删除整段 .turn-link CSS 规则（含 :hover），允许跨行
before = text
css_pat = re.compile(
    r'\.turn-link\{[^}]*\}\s*\.report-item:hover \.turn-link\{[^}]*\}\s*',
    re.S,
)
text = css_pat.sub('', text)
print("CSS 块已移除:", before != text)

# 2) 删除 HTML 模板里的 <div class="turn-link">一键复制文案</div> 整行
lines = text.split('\n')
new_lines = [ln for ln in lines if 'turn-link' not in ln]
print("div 行已移除:", len(new_lines) != len(lines))
text = '\n'.join(new_lines)

with io.open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("完成。剩余 turn-link 出现次数：", text.count("turn-link"))
