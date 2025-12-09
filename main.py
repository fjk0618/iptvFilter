# async_m3u8_parser.py
import os
import re
import queue
import traceback
from concurrent.futures import ThreadPoolExecutor
import httpx
from urllib.parse import urljoin
from doGroup import group_m3u8_file


def get_content(url):
    """
    异步获取URL内容
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36"
    }
    with httpx.Client(headers=headers, timeout=10) as client:
        try:
            response = client.get(url, headers=headers)
            return response.text
        except Exception as e:
            print(f"获取URL内容时出错: {e!r}")
            return None


def download_and_measure_speed(ts_url):
    """
    下载TS文件并计算下载速度
    """
    try:
        start_time = time.time()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36"
        }
        with httpx.Client(headers=headers) as client:
            with client.stream("GET", ts_url, timeout=10) as response:
                if response.status_code == 200:
                    count = 0
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        count += 1
                        if not chunk:
                            break
                        content_length = len(chunk)
                        if count >= 5:
                            break
                    end_time = time.time()

                    # 计算下载速度 (KB/s)
                    download_time = end_time - start_time
                    if download_time > 0:
                        download_speed = (content_length / 1024) / download_time
                        return download_speed
        return None
    except Exception as e:
        print(f"下载文件时出错: {e!r}")
        return None


def process_m3u8_url(line_content, prev_line, index, total):

    """
    处理单个m3u8 URL并提取真实播放地址
    """
    try:
            # 打印处理进度
            progress = (index + 1) / total * 100
            print(f"\r正在处理: {index + 1}/{total} ({progress:.1f}%)", end="", flush=True)

            if line_content.endswith(".m3u8") and "stream1.freetv.fun" in line_content:
                real_play_m3u8_content = get_content(line_content.strip())
                if not real_play_m3u8_content:
                    return None
                results = re.findall(r"^(?!#).*$", real_play_m3u8_content, re.MULTILINE)
                results = list(filter(bool, results))
                if len(results) == 1:
                    real_play_url = results[0]
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36"
                    }
                    # 检查real_play_url播放链接是否可以正常访问
                    with httpx.Client(headers=headers) as client:
                        response = client.get(real_play_url, timeout=7)
                        if response.status_code == 200:
                            play_ts_urls = re.findall(r"^(?!#).*$", response.text, re.MULTILINE)
                            # 下载play_ts_urls中的第一个文件并计算下载速度
                            if play_ts_urls:
                                first_ts_url = play_ts_urls[0]
                                if not first_ts_url.startswith("http"):
                                    first_ts_url = urljoin(real_play_url, first_ts_url)
                                download_speed = download_and_measure_speed(first_ts_url)
                                if download_speed:
                                    print(f"\n下载速度: {download_speed:.2f} KB/s")
                                    if download_speed > 500:
                                        return prev_line, real_play_url
                                else:
                                    print("\n无法测量下载速度")
            return None
    except (httpx.ReadError, httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError, httpx.ReadTimeout):
        pass
    except Exception as e:
        print(f"处理URL时出错: {line_content}, 错误: {e!r},\n{traceback.format_exc()}")
    return None


def parse_m3u8(m3u8_Url: str):
    """
    异步解析m3u8文件并提取播放链接
    """
    play_queue = queue.Queue()
    print("开始解析m3u8文件...")

    # 创建异步HTTP客户端
    m3u8_Url_Content = get_content(m3u8_Url)
    m3u8_Url_Content_lines = m3u8_Url_Content.splitlines()

    # 筛选出需要处理的行
    process_lines = []
    process_lines_info = []
    for line_num, line_content in enumerate(m3u8_Url_Content_lines):
        if not line_content.startswith("#") and line_content:
            prev_line = m3u8_Url_Content_lines[line_num - 1] if line_num > 0 else ""
            process_lines.append((line_content, prev_line))
            process_lines_info.append(line_num)

    total_lines = len(process_lines)
    print(f"总共需要处理 {total_lines} 个URL")

    # 创建线程池
    with ThreadPoolExecutor(max_workers=24) as executor:
        # 创建任务列表
        futures = []
        for index, (line_content, prev_line) in enumerate(process_lines):
            future = executor.submit(process_m3u8_url, line_content, prev_line, index, total_lines)
            futures.append(future)

        # 处理结果
        success_count = 0

        for future in futures:
            result = future.result()
            if result:
                print(f"\n找到有效播放链接: {result[1]}")  # real_play_url
                print(f"频道信息: {result[0]}")  # previous line (channel info)
                play_queue.put(result)
                success_count += 1

        print(f"\n解析完成! 总共处理 {total_lines} 个URL, 成功获取 {success_count} 个有效播放链接")
        return play_queue


def save_results_to_file(play_queue, filename="channels.txt"):
    """
    将结果保存到文件
    """
    total_items = play_queue.qsize()
    print(f"开始保存 {total_items} 个频道到文件 {filename}...")

    saved_count = 0
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"#EXTM3U x-tvg-url=\"https://epg.pw/xmltv/epg_lite.xml\"\n")
        f.write(f"#This file is re-writen by ssson.\n")
        if not total_items:
            return
        while not play_queue.empty():
            channel_info, play_url = play_queue.get()
            f.write(f"{channel_info}\n{play_url}\n")
            saved_count += 1
            # 打印保存进度
            progress = saved_count / total_items * 100
            print(f"\r正在保存: {saved_count}/{total_items} ({progress:.1f}%)", end="", flush=True)

    print(f"\n成功保存 {saved_count} 个频道到文件 {filename}")


if __name__ == "__main__":
    import time

    url = "https://freetv.fun/test_channels_china_new.m3u"
    start_time = time.time()
    print("程序开始运行...")

    # 运行异步函数
    queue_result = parse_m3u8(url)

    print(f"解析耗时: {time.time() - start_time:.2f}秒")
    # 保存结果到文件
    save_results_to_file(queue_result, "test_channels_all_new.m3u8")
    print(f"总耗时: {time.time() - start_time:.2f}秒")

    if os.path.exists("test_channels_all_new.m3u8"):
        group_m3u8_file("test_channels_all_new.m3u8")
        if os.path.exists("group_channels.m3u8"):
            os.remove("test_channels_all_new.m3u8")
            print("已删除test_channels_all_new.m3u8文件")
            print("频道按语言分类成功！")
