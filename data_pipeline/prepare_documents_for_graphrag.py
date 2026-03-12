"""
文件切割腳本 - 將 input/ 的 PDF 切割成 input_graphrag/ 的文本檔案

功能：
1. 讀取 PDF 並提取文本
2. 根據文件類型切割成條款
3. 輸出格式化的 txt 檔案供 GraphRAG 使用
"""

import fitz  # PyMuPDF
import re
import os
from pathlib import Path
from typing import List, Dict, Tuple


class DocumentProcessor:
    """文件處理器"""

    def __init__(self, input_dir: str = "input", output_dir: str = "input_graphrag"):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def read_pdf(self, pdf_path: str, skip_first_page: bool = False) -> str:
        """
        讀取 PDF 並提取文本

        Args:
            pdf_path: PDF 檔案路徑
            skip_first_page: 是否跳過第一頁

        Returns:
            str: 提取的文本
        """
        doc = fitz.open(pdf_path)
        text = ""
        start_page = 1 if skip_first_page else 0

        for page_num in range(start_page, len(doc)):
            page = doc.load_page(page_num)
            text += page.get_text()

        doc.close()
        return text

    def chinese_to_arabic(self, chinese_num: str) -> int:
        """將中文數字轉換為阿拉伯數字"""
        chinese_digits = {
            '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '七': 7, '八': 8, '九': 9, '十': 10
        }

        if chinese_num in chinese_digits:
            return chinese_digits[chinese_num]

        if '十' in chinese_num:
            if chinese_num.startswith('十'):
                if len(chinese_num) == 1:
                    return 10
                else:
                    return 10 + chinese_digits.get(chinese_num[1], 0)
            elif chinese_num.endswith('十'):
                return chinese_digits.get(chinese_num[0], 0) * 10
            else:
                parts = chinese_num.split('十')
                if len(parts) == 2:
                    tens = chinese_digits.get(parts[0], 0) * 10
                    units = chinese_digits.get(parts[1], 0)
                    return tens + units

        return 0

    def chinese_major_to_arabic(self, chinese_num: str) -> int:
        """將主項目的中文大寫數字（壹、貳、參等）轉換為阿拉伯數字"""
        chinese_major_digits = {
            '壹': 1, '貳': 2, '參': 3, '肆': 4, '伍': 5,
            '陸': 6, '柒': 7, '捌': 8, '玖': 9, '拾': 10
        }
        return chinese_major_digits.get(chinese_num, 0)

    def extract_contract_clauses(self, text: str) -> List[Dict]:
        """
        提取契約條款（第一條、第二條等）

        Returns:
            List[Dict]: 條款列表
        """
        pattern = r'第([一二三四五六七八九十\d]+)條\s+([^\n]+)'
        matches = re.findall(pattern, text)
        clauses = []

        clause_positions = []
        for match in re.finditer(pattern, text):
            clause_number = match.group(1)
            clause_title = match.group(2).strip()
            start_pos = match.end()

            clause_positions.append({
                'number': clause_number,
                'title': clause_title,
                'start': start_pos
            })

        for i, clause_info in enumerate(clause_positions):
            if i < len(clause_positions) - 1:
                next_start = clause_positions[i + 1]['start'] - len(clause_positions[i + 1]['title']) - 10
                content = text[clause_info['start']:next_start].strip()
            else:
                content = text[clause_info['start']:].strip()

            clauses.append({
                'number': clause_info['number'],
                'title': clause_info['title'],
                'content': content
            })

        return clauses

    def extract_bidding_clauses(self, text: str) -> List[Dict]:
        """
        提取投標須知條款（一、二、三等）

        Returns:
            List[Dict]: 條款列表
        """
        pattern = r'^([一二三四五六七八九十]+|[一二三四五六七八九十]*十[一二三四五六七八九十]*|[一二三四五六七八九十]*百[一二三四五六七八九十]*)、\s*([^\n]*)'

        matches = list(re.finditer(pattern, text, re.MULTILINE))
        clauses = []
        max_clause_number = 0

        for i, match in enumerate(matches):
            clause_number = match.group(1)
            title = match.group(2).strip()
            start_pos = match.end()

            line_start = text.rfind('\n', 0, match.start()) + 1
            prefix = text[line_start:match.start()]

            if len(prefix) > 2:
                continue

            current_number = self.chinese_to_arabic(clause_number)

            if current_number <= max_clause_number:
                continue

            max_clause_number = current_number

            next_start = None
            for j in range(i + 1, len(matches)):
                next_match = matches[j]
                next_clause_number = next_match.group(1)
                next_current_number = self.chinese_to_arabic(next_clause_number)

                if next_current_number > current_number:
                    next_line_start = text.rfind('\n', 0, next_match.start()) + 1
                    next_prefix = text[next_line_start:next_match.start()]
                    if len(next_prefix) <= 2:
                        next_start = next_match.start()
                        break

            if next_start is not None:
                content = text[start_pos:next_start].strip()
            else:
                content = text[start_pos:].strip()

            full_content = title
            if content.strip():
                full_content += '\n' + content

            clauses.append({
                'number': clause_number,
                'title': title if title else clause_number,  # 如果標題為空，使用編號
                'content': full_content.strip()
            })

        return clauses

    def extract_supplement_clauses(self, text: str) -> List[Dict]:
        """
        提取補充投標須知條款（第一條、第二條等）

        Returns:
            List[Dict]: 條款列表
        """
        # 使用與契約相同的模式
        pattern = r'第([一二三四五六七八九十\d]+)條\s+([^\n]*)'

        matches = list(re.finditer(pattern, text))
        clauses = []

        for i, match in enumerate(matches):
            clause_number = match.group(1)
            title = match.group(2).strip()
            start_pos = match.end()

            if i < len(matches) - 1:
                next_start = matches[i + 1].start()
                content = text[start_pos:next_start].strip()
            else:
                content = text[start_pos:].strip()

            # 如果標題為空，嘗試從內容第一行提取
            if not title:
                content_lines = content.split('\n')
                if content_lines:
                    first_line = content_lines[0].strip()
                    # 如果第一行不太長（<100字），作為標題
                    if len(first_line) < 100:
                        title = first_line
                        # 移除第一行，剩餘作為內容
                        content = '\n'.join(content_lines[1:]).strip()
                    else:
                        # 否則使用編號作為標題
                        title = f"第{clause_number}條"

            clauses.append({
                'number': clause_number,
                'title': title,
                'content': content
            })

        return clauses

    def extract_appendix_a_clauses(self, text: str) -> List[Dict]:
        """
        提取附錄A條款（壹、貳、參等及子項目）

        Returns:
            List[Dict]: 條款列表
        """
        major_pattern = r'^([壹貳參肆伍陸柒捌玖拾]+)、\s*([^\n]+)'
        minor_pattern = r'^\s*([一二三四五六七八九十百千]+)、\s*([^\n]*)'

        major_matches = list(re.finditer(major_pattern, text, re.MULTILINE))
        clauses = []

        for i, major_match in enumerate(major_matches):
            major_number = major_match.group(1)
            major_title = major_match.group(2).strip()
            major_start = major_match.end()

            if i < len(major_matches) - 1:
                major_end = major_matches[i + 1].start()
            else:
                major_end = len(text)

            major_content = text[major_start:major_end]

            minor_matches = list(re.finditer(minor_pattern, major_content, re.MULTILINE))

            if minor_matches:
                for j, minor_match in enumerate(minor_matches):
                    minor_number = minor_match.group(1)
                    minor_title = minor_match.group(2).strip()
                    minor_start = minor_match.end()

                    if j < len(minor_matches) - 1:
                        minor_end = minor_matches[j + 1].start()
                    else:
                        minor_end = len(major_content)

                    minor_content = major_content[minor_start:minor_end].strip()

                    full_content = minor_title
                    if minor_content:
                        full_content += '\n' + minor_content

                    major_num = self.chinese_major_to_arabic(major_number)
                    minor_num = self.chinese_to_arabic(minor_number)

                    clauses.append({
                        'number': f"{major_num}_{minor_num}",
                        'major_number': major_number,
                        'major_title': major_title,
                        'minor_number': minor_number,
                        'title': minor_title if minor_title else f"{major_title} - {minor_number}",
                        'content': full_content.strip()
                    })
            else:
                major_num = self.chinese_major_to_arabic(major_number)
                clauses.append({
                    'number': str(major_num),
                    'major_number': major_number,
                    'major_title': major_title,
                    'title': major_title,
                    'content': major_content.strip()
                })

        return clauses

    def split_bidding_document(self, text: str) -> Tuple[str, str]:
        """
        分割投標須知和補充投標須知

        Returns:
            Tuple[str, str]: (投標須知文本, 補充投標須知文本)
        """
        supplement_pattern = r'補充投標須知\(準用最有利標\)'
        match = re.search(supplement_pattern, text)

        if match:
            split_pos = match.start()
            bidding_notice = text[:split_pos].strip()
            supplement_notice = text[split_pos:].strip()
            return bidding_notice, supplement_notice
        else:
            return text.strip(), ""

    def save_clause_to_file(self, clause: Dict, filename: str, document_type: str):
        """
        儲存條款到檔案

        Args:
            clause: 條款字典
            filename: 輸出檔名
            document_type: 文件類型（contract/bidding_notice/supplement_notice/appendix_a）
        """
        filepath = self.output_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            if document_type == "contract":
                f.write(f"文件: 工程契約\n")
                f.write(f"條款編號: {clause['number']}\n")
                f.write(f"主題: {clause['title']}\n")
                f.write(f"\n內容:\n")
                f.write(clause['content'])

            elif document_type == "bidding_notice":
                f.write(f"文件: 投標須知\n")
                f.write(f"條款編號: {clause['number']}\n")
                f.write(f"標題: {clause['title']}\n")
                f.write(f"\n內容:\n")
                f.write(clause['content'])

            elif document_type == "supplement_notice":
                f.write(f"文件: 補充投標須知(準用最有利標)\n")
                f.write(f"條款編號: {clause['number']}\n")
                f.write(f"\n內容:\n")
                f.write(clause['content'])

            elif document_type == "appendix_a":
                f.write(f"文件: 投標須知附錄A\n")
                f.write(f"條款編號: {clause['number']}\n")
                f.write(f"主項目: {clause.get('major_title', '')}\n")
                f.write(f"標題: {clause['title']}\n")
                f.write(f"\n內容:\n")
                f.write(clause['content'])

    def process_contract(self, pdf_path: str):
        """處理契約文件"""
        print(f"\n處理契約文件: {pdf_path}")
        text = self.read_pdf(pdf_path, skip_first_page=True)
        clauses = self.extract_contract_clauses(text)

        print(f"提取到 {len(clauses)} 個契約條款")

        for clause in clauses:
            filename = f"clause_{clause['number']}.txt"
            self.save_clause_to_file(clause, filename, "contract")
            print(f"  儲存: {filename}")

        return len(clauses)

    def process_bidding_document(self, pdf_path: str):
        """處理投標須知文件（包含投標須知和補充投標須知）"""
        print(f"\n處理投標須知文件: {pdf_path}")
        text = self.read_pdf(pdf_path, skip_first_page=False)

        bidding_text, supplement_text = self.split_bidding_document(text)

        total_count = 0

        # 處理投標須知
        if bidding_text:
            clauses = self.extract_bidding_clauses(bidding_text)
            print(f"提取到 {len(clauses)} 個投標須知條款")

            for clause in clauses:
                filename = f"bidding_notice_{clause['number']}.txt"
                self.save_clause_to_file(clause, filename, "bidding_notice")
                print(f"  儲存: {filename}")

            total_count += len(clauses)

        # 處理補充投標須知
        if supplement_text:
            clauses = self.extract_supplement_clauses(supplement_text)
            print(f"提取到 {len(clauses)} 個補充投標須知條款")

            for clause in clauses:
                filename = f"supplement_notice_{clause['number']}.txt"
                self.save_clause_to_file(clause, filename, "supplement_notice")
                print(f"  儲存: {filename}")

            total_count += len(clauses)

        return total_count

    def process_appendix_a(self, pdf_path: str):
        """處理投標須知附錄A"""
        print(f"\n處理投標須知附錄A: {pdf_path}")
        text = self.read_pdf(pdf_path, skip_first_page=True)
        clauses = self.extract_appendix_a_clauses(text)

        print(f"提取到 {len(clauses)} 個附錄A條款")

        for clause in clauses:
            filename = f"appendix_a_{clause['number']}.txt"
            self.save_clause_to_file(clause, filename, "appendix_a")
            print(f"  儲存: {filename}")

        return len(clauses)


def main():
    """主程式"""
    processor = DocumentProcessor(
        input_dir="/home/boya/Sino_ISO/contracts/input",
        output_dir="/home/boya/Sino_ISO/contracts/input_graphrag"
    )

    # 處理各類文件
    total_files = 0

    # 1. 契約文件
    contract_path = processor.input_dir / "03_00臺中捷運藍線建設計畫BD03標細部設計及監造委託技術服務契約-修正版.pdf"
    if contract_path.exists():
        count = processor.process_contract(str(contract_path))
        total_files += count

    # 2. 投標須知文件（包含補充投標須知）
    bidding_path = processor.input_dir / "02-00_投標須知(BD03)_臺中市政府投標須知範本-適用及準用最有利標-修正.pdf"
    if bidding_path.exists():
        count = processor.process_bidding_document(str(bidding_path))
        total_files += count

    # 3. 投標須知附錄A
    appendix_path = processor.input_dir / "02-01_投標須知_附錄A_評選辦法.pdf"
    if appendix_path.exists():
        count = processor.process_appendix_a(str(appendix_path))
        total_files += count

    print(f"\n完成！共產生 {total_files} 個文本檔案")
    print(f"輸出目錄: {processor.output_dir}")


if __name__ == "__main__":
    main()
