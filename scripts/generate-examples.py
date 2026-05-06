#!/usr/bin/env python3
"""
🦋 芭德卡特 - 批量生成单词例句脚本
使用 OpenClaw 为 CSV 单词表生成例句
"""

import csv
import sys
import json
from datetime import datetime

# 配置
INPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else 'input-words.csv'
OUTPUT_FILE = sys.argv[2] if len(sys.argv) > 2 else f'output-words-{datetime.now().strftime("%Y%m%d-%H%M%S")}.csv'
BATCH_SIZE = 50  # 每批处理多少个单词

def read_words(input_file):
    """读取输入 CSV"""
    words = []
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2:
                word = row[0].strip()
                meaning = row[1].strip()
                # 如果已有例句，保留
                example = row[2].strip() if len(row) > 2 else ''
                words.append({
                    'word': word,
                    'meaning': meaning,
                    'example': example
                })
    return words

def generate_example_batch(words_batch):
    """
    为一批单词生成例句
    返回格式：[(word, example), ...]
    """
    # 构建提示词
    word_list = '\n'.join([f"- {w['word']}: {w['meaning']}" for w in words_batch])
    
    prompt = f"""请为以下英语单词生成简单、地道的例句：

{word_list}

要求：
1. 每个例句简短（10-20 个单词）
2. 适合英语初学者
3. 只返回 JSON 格式，不要任何解释
4. 格式：{{"word": "例句"}}

示例输出：
{{
  "abandon": "He decided to abandon the project.",
  "ability": "She has the ability to learn quickly."
}}

请严格按 JSON 格式返回："""
    
    return prompt

def main():
    print(f"🦋 芭德卡特例句生成器")
    print(f"====================")
    print(f"输入：{INPUT_FILE}")
    print(f"输出：{OUTPUT_FILE}")
    print(f"批次大小：{BATCH_SIZE}")
    print()
    
    # 读取单词
    words = read_words(INPUT_FILE)
    print(f"📚 读取到 {len(words)} 个单词")
    
    # 过滤出需要生成的单词
    words_to_generate = [w for w in words if not w['example']]
    words_already_have = [w for w in words if w['example']]
    
    print(f"✨ 需要生成：{len(words_to_generate)} 个")
    print(f"✅ 已有例句：{len(words_already_have)} 个")
    print()
    
    if not words_to_generate:
        print("🎉 所有单词都已有例句！")
        # 仍然输出完整文件
        with open(OUTPUT_FILE, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            for w in words:
                writer.writerow([w['word'], w['meaning'], w['example']])
        print(f"✅ 输出到：{OUTPUT_FILE}")
        return
    
    # 分批处理
    batches = [words_to_generate[i:i+BATCH_SIZE] for i in range(0, len(words_to_generate), BATCH_SIZE)]
    
    print(f"📦 分成 {len(batches)} 批处理")
    print()
    
    all_results = {}
    
    for idx, batch in enumerate(batches, 1):
        print(f"🦋 处理第 {idx}/{len(batches)} 批 ({len(batch)} 个单词)...")
        
        # 生成提示词
        prompt = generate_example_batch(batch)
        
        # 输出提示词（让外部工具调用）
        print(f"📝 提示词：")
        print(prompt)
        print()
        print(f"---WAIT_FOR_OPENCLAW_RESPONSE---")
        print()
        
        # 等待用户输入响应（从 stdin 读取 OpenClaw 生成的 JSON）
        print("请输入 OpenClaw 返回的 JSON 响应（以空行结束）：")
        response_lines = []
        while True:
            line = input()
            if line.strip() == '':
                break
            response_lines.append(line)
        
        response_text = '\n'.join(response_lines).strip()
        
        # 解析 JSON
        try:
            # 尝试提取 JSON 部分
            import re
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                response_text = json_match.group()
            
            batch_results = json.loads(response_text)
            all_results.update(batch_results)
            print(f"✅ 本批成功生成 {len(batch_results)} 个例句")
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失败：{e}")
            print(f"   原始响应：{response_text[:200]}...")
            # 继续下一批
    
    # 合并结果
    print()
    print("🔧 合并结果...")
    
    final_words = []
    for w in words:
        if w['example']:
            # 已有例句
            final_words.append(w)
        elif w['word'] in all_results:
            # 新生成的
            final_words.append({
                'word': w['word'],
                'meaning': w['meaning'],
                'example': all_results[w['word']]
            })
        else:
            # 生成失败，保留空例句
            final_words.append(w)
    
    # 输出
    with open(OUTPUT_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        for w in final_words:
            writer.writerow([w['word'], w['meaning'], w['example']])
    
    print(f"✅ 完成！输出到：{OUTPUT_FILE}")
    print(f"📊 统计：")
    print(f"   总单词数：{len(final_words)}")
    print(f"   有例句：{len([w for w in final_words if w['example']])}")
    print(f"   无例句：{len([w for w in final_words if not w['example']])}")

if __name__ == '__main__':
    main()
