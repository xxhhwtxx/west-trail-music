"""
West Trail Music — 桌面窗口启动器
自动分配端口，PyWebView 内嵌浏览器窗口
"""
import sys
import time
import socket
import threading
import traceback

import uvicorn
import webview
from server import app


def get_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run_server(port: int):
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


def main():
    port = get_free_port()

    server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    server_thread.start()

    # 等待服务就绪
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
            s.close()
            break
        except OSError:
            time.sleep(0.3)
    else:
        print("[错误] 服务启动超时，请重试")
        input("按回车键退出...")
        sys.exit(1)

    print(f"服务已启动: http://127.0.0.1:{port}")

    webview.create_window(
        "West Trail Music",
        f"http://127.0.0.1:{port}",
        width=1100,
        height=750,
        resizable=True,
        background_color="#000000",
    )
    webview.start()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        input("按回车键退出...")
