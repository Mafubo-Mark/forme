# 完整源碼與接手說明

更新：2026-10-17。本次將 Mac 後端完整源碼加入原 Mafubo-Mark/forme 倉庫，不再只有前端和增量補丁。本機流水線已按要求關閉；推送代碼不代表自動啟動本機或升級伺服器。

## 目錄

| 目錄 | 用途 |
|---|---|
| dist/ | 已有的使用者前端、管理頁、語系與3D預覽資源 |
| cloud/、database/ | 已有的雲端API、帳戶／訂單／上傳資料與部署程式 |
| forme-backend/src/forme_backend/ | 完整Mac API、持久任務、COLMAP、點雲保護套隊列及雲橋接 |
| forme-backend/operator/ | 新版三步工作流控制台 |
| forme-backend/scripts/scanfit/ | 點雲全高適配、上緣、螺栓開孔、網格檢查、試配件與STL打包 |
| forme-backend/scripts/ | 標尺、點雲證據準備、CLI、一鍵啟停及其他後端工具 |
| forme-backend/web/ | 原本機客戶頁靜態快照，供本機原有入口相容使用；雲端公開站點仍部署dist/ |
| work-buddy-handoff/automation/ | WorkBuddy MCP與舊版概念適配工具 |
| work-buddy-handoff/skills/forme-scan-workflow/ | WorkBuddy／Codex／其他Agent的技能入口及操作參考 |
| work-buddy-handoff/production-bases/06/ | 生產生成器使用的純模板左右對稱基準與完整性清單；不包含使用者點雲 |
| research/ | 81個歷史研究腳本，保留原始路徑結構；不是當前生產入口 |
| docs/SOURCE_INVENTORY_2026-10-17.json | 本次同步源檔清單、大小及SHA256 |

`worker/local-backend-overlay/` 是歷史增量包。新的本機維護以 forme-backend/ 為準，不要再用舊增量覆蓋新版本。

## 新流程

閱讀 [點雲主流程](../forme-backend/SCAN_WORKFLOW_ZH.md) 與 [Agent Skill](../work-buddy-handoff/skills/forme-scan-workflow/SKILL.md)。

點雲重建 → 本單尺度／剛體定軸／上緣／下緣／螺栓證據 → 幾何確認 → 全高適配、開孔、檢查 → 毫米STL、試配件和ZIP。默認不使用混元。目前首個支持的樣式為06通風模板。

本輪已通過24項後端測試、5項媒體載入測試，並用真實已複核點雲在隔離目錄完成生產調度至STL與API下載回放。實物良好試戴反饋只對原V5文件有效，不自動套給重建版本或下一單。

## 在其他電腦恢復

1. Python 3.11+：在 forme-backend 下建立虛擬環境，安裝 `pip install -e '.[test]'`。幾何環境需另外安裝 numpy、scipy、trimesh、pycolmap、plyfile、opencv-python、Pillow；Blender和COLMAP為外部工具。
2. 依實際環境設定 FORME_DATA_DIR、FORME_GEOMETRY_PYTHON、FORME_BLENDER、FORME_COLMAP、FORME_FFMPEG、FORME_FFPROBE。原一鍵腳本含這台Mac的工具預設路徑，搬機前需調整。
3. 管理令牌、使用者登入密鑰、雲橋接配置、SSH金鑰均在新機私下設定。參照既有部署說明，不能從Git取得正式憑據。
4. 此倉庫包含06對稱生產基準；完整七組原始列印模板庫需從專案資產備份恢復。templates/catalog.json及舊腳本仍含原工作區路徑，若使用舊模板入口，應按新位置重新配置／登記。
5. 源碼不含使用者影片和任務資料。新訂單從實際雲端資料同步，或從授權備份恢復；不要把空白資料目錄當作已有任務。
6. 需要運行時才使用 start-all.command／run-local.sh。目前已按使用者要求停止，不因拉取代碼而啟動。

歷史research腳本依賴當時的資料、FreeCAD／CGAL等工具及既有路徑，不能直接當通用新訂單生成器。逐單產生的實驗腳本位於私有data目錄，未納入公開倉庫；其中可重用方法已整理到scripts/scanfit。

## 明確排除

登入憑據、API密鑰、私有連線配置、影片／照片／點雲、個案模型、資料庫、日誌、虛擬環境與下載的工具二進位均不進Git。純樣式模板基準和既有公開前端預覽資源屬必要專案資產，不是個案生成模型。
