"""
文件切割腳本 v2 - 將 PDF 切割成分層條款 txt 檔案

輸出格式（工程契約）：
  clause_{X}.txt            第X條 (第1層)
  clause_{X}_{Y}.txt        第X條 > Y、 (第2層)
  clause_{X}_{Y}_{Z}.txt    第X條 > Y、 > (Z) (第3層)

輸出格式（投標須知）：
  bidding_notice_{中文}.txt  單層

輸出格式（投標須知附錄A）：
  appendix_a_{N}.txt         壹貳參... (第1層)
  appendix_a_{N}_{M}.txt     子項目 (第2層)
"""

import re
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import fitz  # PyMuPDF


# ============================================================
# PDF 刪除線過濾
# ============================================================

def extract_text_without_strikethrough(page) -> str:
    """提取頁面文字，跳過有刪除線的文字（flags & 16）"""
    text_dict = page.get_text("dict")
    clean_text = ""
    for block in text_dict["blocks"]:
        if "lines" in block:
            for line in block["lines"]:
                line_text = ""
                for span in line["spans"]:
                    if not bool(span.get("flags", 0) & 16):
                        line_text += span["text"]
                    else:
                        print(f"  跳過刪除線文字: {span['text'][:30]}")
                clean_text += line_text + "\n"
    return clean_text


# ============================================================
# 中文數字轉換工具
# ============================================================

CHINESE_NUM = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
}

CHINESE_MAJOR_NUM = {
    '壹': 1, '貳': 2, '參': 3, '肆': 4, '伍': 5,
    '陸': 6, '柒': 7, '捌': 8, '玖': 9, '拾': 10,
}

ARABIC_TO_CHINESE = {v: k for k, v in CHINESE_NUM.items()}


def chinese_to_arabic(s: str) -> int:
    """將中文數字字串轉為阿拉伯數字（支援 一, 十, 十一, 二十, 二十一 等）"""
    s = s.strip()
    if not s:
        return 0
    if s in CHINESE_NUM:
        return CHINESE_NUM[s]
    if '十' in s:
        if s == '十':
            return 10
        if s.startswith('十'):
            return 10 + CHINESE_NUM.get(s[1:], 0)
        if s.endswith('十'):
            return CHINESE_NUM.get(s[:-1], 0) * 10
        parts = s.split('十', 1)
        tens = CHINESE_NUM.get(parts[0], 0) * 10
        units = CHINESE_NUM.get(parts[1], 0) if parts[1] else 0
        return tens + units
    return 0


def num_to_chinese(n: int) -> str:
    """將阿拉伯數字轉回中文（1-99，用於條款路徑顯示）"""
    if n in ARABIC_TO_CHINESE:
        return ARABIC_TO_CHINESE[n]
    if n == 10:
        return '十'
    if n < 20:
        return '十' + ARABIC_TO_CHINESE.get(n - 10, '')
    tens = n // 10
    units = n % 10
    result = ARABIC_TO_CHINESE.get(tens, '') + '十'
    if units:
        result += ARABIC_TO_CHINESE.get(units, '')
    return result


# ============================================================
# PDF 讀取
# ============================================================

def read_pdf(path: str, skip_first_page: bool = False, skip_strikethrough: bool = True) -> str:
    """讀取 PDF，預設跳過刪除線文字"""
    doc = fitz.open(path)
    text = ''
    start = 1 if skip_first_page else 0
    for i in range(start, len(doc)):
        page = doc.load_page(i)
        if skip_strikethrough:
            text += extract_text_without_strikethrough(page)
        else:
            text += page.get_text()
    doc.close()
    return text


# ============================================================
# 工程契約解析（三層）
# ============================================================

# 第X條
ARTICLE_PAT = re.compile(r'第([一二三四五六七八九十百\d]+)條\s+([^\n]*)')
# 一、二、... (行首，縮排不超過4個空白，允許前置符號如 ■□✓●)
L2_PAT = re.compile(r'(?m)^[ \t]{0,4}[^\w\u4e00-\u9fff\n]{0,3}([一二三四五六七八九十]+)、[ \t]*(.*)')
# (一)(二)... 或 （一）（二）...（全形/半形括號皆支援）
L3_PAT = re.compile(r'[（(]([一二三四五六七八九十]+)[）)][ \t]*(.*)')


def _parse_l3_items(body: str) -> List[Dict]:
    """從 level-2 的 body 中解析 level-3 items"""
    matches = list(L3_PAT.finditer(body))
    items = []
    for i, m in enumerate(matches):
        zh = m.group(1)
        intro = m.group(2).strip()
        content_start = m.end()
        content_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        extra = body[content_start:content_end].strip()
        full_text = intro + (' ' + extra if extra else '')
        items.append({
            'zh': zh,
            'num': chinese_to_arabic(zh),
            'text': full_text.strip(),
        })
    return items


def _parse_l2_items(body: str) -> List[Dict]:
    """從第X條的 body 中解析 level-2 items"""
    matches = list(L2_PAT.finditer(body))
    items = []
    for i, m in enumerate(matches):
        zh = m.group(1)
        intro = m.group(2).strip()
        sub_start = m.end()
        sub_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sub_body = body[sub_start:sub_end]

        # intro text = 從 sub_start 到第一個 L3 match（或 sub_end）
        first_l3 = L3_PAT.search(sub_body)
        if first_l3:
            intro_extra = sub_body[:first_l3.start()].strip()
        else:
            intro_extra = sub_body.strip()

        full_intro = intro + (' ' + intro_extra if intro_extra else '')

        items.append({
            'zh': zh,
            'num': chinese_to_arabic(zh),
            'intro': full_intro.strip(),
            'l3': _parse_l3_items(sub_body),
        })
    return items


def parse_contract(text: str) -> List[Dict]:
    """
    解析工程契約文字，回傳所有條款（三層），每筆含完整輸出資訊。
    """
    results = []
    art_matches = list(ARTICLE_PAT.finditer(text))

    for ai, am in enumerate(art_matches):
        art_zh = am.group(1)
        art_num = chinese_to_arabic(art_zh) if not art_zh.isdigit() else int(art_zh)
        art_title = am.group(2).strip()
        art_start = am.end()
        art_end = art_matches[ai + 1].start() if ai + 1 < len(art_matches) else len(text)
        art_body = text[art_start:art_end]

        art_path = f'第{art_zh}條'
        art_line = f'[第{art_zh}條] {art_title}'

        # Level 1
        results.append({
            'level': 1,
            'filename': f'clause_{art_num}.txt',
            'header': {
                '文件': '工程契約',
                '條款路徑': art_path,
                '條款編號': str(art_num),
                '主題': art_title,
                '層級': '第1層',
                '父條款': '無',
            },
            'content': art_line,
        })

        l2_items = _parse_l2_items(art_body)

        for l2 in l2_items:
            l2_path = f'{art_path} > {l2["zh"]}、'
            l2_line = f'  [{l2_path}] {l2["intro"]}'
            l2_content = art_line + '\n' + l2_line

            # Level 2
            results.append({
                'level': 2,
                'filename': f'clause_{art_num}_{l2["num"]}.txt',
                'header': {
                    '文件': '工程契約',
                    '條款路徑': l2_path,
                    '條款編號': f'{art_num}.{l2["num"]}',
                    '主題': art_title,
                    '層級': '第2層',
                    '父條款': str(art_num),
                },
                'content': l2_content,
            })

            for l3 in l2['l3']:
                l3_path = f'{l2_path} > ({l3["zh"]})'
                l3_line = f'    [{l3_path}] {l3["text"]}'
                l3_content = l2_content + '\n' + l3_line

                # Level 3
                results.append({
                    'level': 3,
                    'filename': f'clause_{art_num}_{l2["num"]}_{l3["num"]}.txt',
                    'header': {
                        '文件': '工程契約',
                        '條款路徑': l3_path,
                        '條款編號': f'{art_num}.{l2["num"]}.{l3["num"]}',
                        '主題': art_title,
                        '層級': '第3層',
                        '父條款': f'{art_num}.{l2["num"]}',
                    },
                    'content': l3_content,
                })

    return results


# ============================================================
# 投標須知解析（單層）
# ============================================================

BIDDING_L1_PAT = re.compile(
    r'(?m)^[ \t]{0,2}([一二三四五六七八九十百千]+)、[ \t]*([^\n]*)'
)


def _is_valid_sequence(current: int, prev: int) -> bool:
    """確保條款編號是遞增的（避免內文中的 一、 被誤判）"""
    return current == prev + 1 or (prev == 0 and current == 1)


def parse_bidding_notice(text: str) -> List[Dict]:
    """解析投標須知（單層，一、二、三...）"""
    matches = list(BIDDING_L1_PAT.finditer(text))
    results = []
    prev_num = 0
    valid_matches = []

    # 過濾：只保留行首且編號遞增的條款
    for m in matches:
        line_start = text.rfind('\n', 0, m.start()) + 1
        prefix = text[line_start:m.start()]
        if len(prefix) > 2:
            continue
        num = chinese_to_arabic(m.group(1))
        if num <= prev_num:
            continue
        prev_num = num
        valid_matches.append(m)

    for i, m in enumerate(valid_matches):
        zh = m.group(1)
        title = m.group(2).strip() or zh
        content_start = m.end()
        content_end = valid_matches[i + 1].start() if i + 1 < len(valid_matches) else len(text)
        body = text[content_start:content_end].strip()

        full_content = title + ('\n' + body if body else '')

        results.append({
            'filename': f'bidding_notice_{zh}.txt',
            'header': {
                '文件': '投標須知',
                '條款編號': zh,
                '標題': title,
            },
            'content': full_content,
        })

    return results


# ============================================================
# 補充投標須知解析（單層，第X條，中文數字檔名）
# ============================================================

SUPP_ART_PAT = re.compile(r'第([一二三四五六七八九十\d]+)條\s+([^\n]*)')


def parse_supplement_notice(text: str) -> List[Dict]:
    """解析補充投標須知（第X條，單層，檔名保留中文數字）"""
    matches = list(SUPP_ART_PAT.finditer(text))
    results = []
    for i, m in enumerate(matches):
        zh = m.group(1)
        title = m.group(2).strip()
        content_start = m.end()
        content_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[content_start:content_end].strip()

        results.append({
            'filename': f'supplement_notice_{zh}.txt',
            'header': {
                '文件': '補充投標須知(準用最有利標)',
                '條款編號': zh,
                '主題': title,
            },
            'content': body,
        })
    return results


# ============================================================
# 投標須知附錄A解析（兩層）
# ============================================================

APPENDIX_L1_PAT = re.compile(r'(?m)^([壹貳參肆伍陸柒捌玖拾]+)、[ \t]*([^\n]+)')
APPENDIX_L2_PAT = re.compile(r'(?m)^[ \t]{0,4}([一二三四五六七八九十]+)、[ \t]*([^\n]*)')


def parse_appendix_a(text: str) -> List[Dict]:
    """解析投標須知附錄A（壹貳參... > 一二三... 兩層）"""
    results = []
    l1_matches = list(APPENDIX_L1_PAT.finditer(text))

    for i, lm in enumerate(l1_matches):
        major_zh = lm.group(1)
        major_num = CHINESE_MAJOR_NUM.get(major_zh, 0)
        major_title = lm.group(2).strip()
        body_start = lm.end()
        body_end = l1_matches[i + 1].start() if i + 1 < len(l1_matches) else len(text)
        body = text[body_start:body_end]

        major_path = major_zh
        major_label = f'{major_zh}、{major_title}'

        # Level 1
        results.append({
            'level': 1,
            'filename': f'appendix_a_{major_num}.txt',
            'header': {
                '文件': '投標須知附錄A',
                '條款路徑': major_path,
                '條款編號': str(major_num),
                '主項目': major_label,
                '層級': '第1層',
            },
            'content': body.strip(),
        })

        # Level 2
        l2_matches = list(APPENDIX_L2_PAT.finditer(body))
        for j, sm in enumerate(l2_matches):
            sub_zh = sm.group(1)
            sub_num = chinese_to_arabic(sub_zh)
            sub_title = sm.group(2).strip()
            sub_start = sm.end()
            sub_end = l2_matches[j + 1].start() if j + 1 < len(l2_matches) else len(body)
            sub_body = body[sub_start:sub_end].strip()

            full_content = (sub_title + '\n' + sub_body).strip() if sub_body else sub_title

            results.append({
                'level': 2,
                'filename': f'appendix_a_{major_num}_{sub_num}.txt',
                'header': {
                    '文件': '投標須知附錄A',
                    '條款路徑': f'{major_zh} > {sub_zh}',
                    '條款編號': f'{major_num}.{sub_num}',
                    '主項目': major_label,
                    '子項目': f'{sub_zh}、',
                    '層級': '第2層',
                },
                'content': full_content,
            })

    return results


# ============================================================
# 檔案寫入
# ============================================================

def write_item(item: Dict, output_dir: Path):
    """將一個條款 item 寫成 txt 檔案"""
    filepath = output_dir / item['filename']
    with open(filepath, 'w', encoding='utf-8') as f:
        for key, val in item['header'].items():
            f.write(f'{key}: {val}\n')
        f.write('\n內容:\n')
        f.write(item['content'])


# ============================================================
# 主程式
# ============================================================

def process_all(
    contract_pdf: Optional[str] = None,
    bidding_pdf: Optional[str] = None,
    appendix_pdf: Optional[str] = None,
    output_dir: str = 'input_graphrag',
    dry_run: bool = False,
):
    """
    執行全部文件處理。

    Args:
        contract_pdf: 工程契約 PDF 路徑
        bidding_pdf:  投標須知 PDF 路徑（含補充投標須知）
        appendix_pdf: 投標須知附錄A PDF 路徑
        output_dir:   輸出目錄
        dry_run:      只解析不寫檔，用於測試
    """
    out = Path(output_dir)
    if not dry_run:
        out.mkdir(exist_ok=True)

    total = 0

    if contract_pdf and Path(contract_pdf).exists():
        print(f'\n[契約] 讀取 {contract_pdf}')
        text = read_pdf(contract_pdf, skip_first_page=True)
        items = parse_contract(text)
        print(f'  解析到 {len(items)} 個條款節點'
              f'（L1:{sum(1 for i in items if i["level"]==1)}'
              f' L2:{sum(1 for i in items if i["level"]==2)}'
              f' L3:{sum(1 for i in items if i["level"]==3)}）')
        if not dry_run:
            for item in items:
                write_item(item, out)
        total += len(items)

    if bidding_pdf and Path(bidding_pdf).exists():
        print(f'\n[投標須知] 讀取 {bidding_pdf}')
        text = read_pdf(bidding_pdf, skip_first_page=False)

        # 分割投標須知 / 補充投標須知
        split_pat = re.compile(r'補充投標須知')
        split_m = split_pat.search(text)
        bidding_text = text[:split_m.start()].strip() if split_m else text
        supplement_text = text[split_m.start():].strip() if split_m else ''

        b_items = parse_bidding_notice(bidding_text)
        print(f'  投標須知 {len(b_items)} 個條款')
        if not dry_run:
            for item in b_items:
                write_item(item, out)
        total += len(b_items)

        if supplement_text:
            # 補充投標須知：第X條 單層，中文數字檔名（同 reference.py）
            s_items = parse_supplement_notice(supplement_text)
            print(f'  補充投標須知 {len(s_items)} 個條款')
            if not dry_run:
                for item in s_items:
                    write_item(item, out)
            total += len(s_items)

    if appendix_pdf and Path(appendix_pdf).exists():
        print(f'\n[附錄A] 讀取 {appendix_pdf}')
        text = read_pdf(appendix_pdf, skip_first_page=True)
        items = parse_appendix_a(text)
        print(f'  解析到 {len(items)} 個條款節點'
              f'（L1:{sum(1 for i in items if i["level"]==1)}'
              f' L2:{sum(1 for i in items if i["level"]==2)}）')
        if not dry_run:
            for item in items:
                write_item(item, out)
        total += len(items)

    print(f'\n完成！共產生 {total} 個條款檔案 → {output_dir}')
    return total


def main():
    import argparse

    BASE = Path('/home/boya/Sino_ISO/contracts')

    parser = argparse.ArgumentParser(description='文件切割腳本 v2')
    parser.add_argument('--contract',  default=str(BASE / 'input/03_00臺中捷運藍線建設計畫BD03標細部設計及監造委託技術服務契約-修正版.pdf'))
    parser.add_argument('--bidding',   default=str(BASE / 'input/02-00_投標須知(BD03)_臺中市政府投標須知範本-適用及準用最有利標-修正.pdf'))
    parser.add_argument('--appendix',  default=str(BASE / 'input/02-01_投標須知_附錄A_評選辦法.pdf'))
    parser.add_argument('--output',    default=str(BASE / 'input_graphrag_v2'))
    parser.add_argument('--dry-run',   action='store_true', help='只解析，不寫檔')
    args = parser.parse_args()

    process_all(
        contract_pdf=args.contract,
        bidding_pdf=args.bidding,
        appendix_pdf=args.appendix,
        output_dir=args.output,
        dry_run=args.dry_run,
    )


if __name__ == '__main__':
    main()
