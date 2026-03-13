"""
應用程式入口點

PyInstaller 打包時以此檔案為入口。
處理 PyInstaller 路徑修正，確保所有子模組都能正確 import。
"""

import os
import sys
from pathlib import Path


def _setup_ssl():
    """設定 SSL 憑證路徑（解決 PyInstaller 打包後 Neo4j Aura 連線問題）"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包後：從解壓目錄載入憑證
        base_dir = Path(sys._MEIPASS)
        cert_file = base_dir / "certifi" / "cacert.pem"
        if cert_file.exists():
            os.environ["SSL_CERT_FILE"] = str(cert_file)
            os.environ["REQUESTS_CA_BUNDLE"] = str(cert_file)


def _setup_paths():
    """修正 PyInstaller 打包環境下的 sys.path"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包後：sys._MEIPASS 是解壓臨時目錄
        base_dir = Path(sys._MEIPASS)

        # 將工作目錄切到使用者家目錄下的應用目錄（可寫入）
        app_data = Path.home() / "SinoISO_Audit"
        app_data.mkdir(exist_ok=True)
        os.chdir(app_data)
    else:
        # 開發模式：contracts/ 目錄
        base_dir = Path(__file__).parent.parent

    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))


def main():
    _setup_ssl()  # 必須在任何網路連線之前設定
    _setup_paths()

    # 延遲 import，確保 path 修正完成後才載入 GUI
    from app.gui.app_window import AuditApp

    app = AuditApp()
    app.mainloop()


if __name__ == "__main__":
    main()
