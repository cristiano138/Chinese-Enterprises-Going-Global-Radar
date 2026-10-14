@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ============================================================
echo   出海合规雷达 —— 数据管线一键重跑
echo ============================================================
echo.
echo   顺序：fetch_eu -^> fetch_us -^> merge_corpus -^> check_links
echo         -^> enrich_cn -^> make_overview -^> make_todo_eu
echo.
echo   注意：fetch_* 需要联网；enrich_cn 需要 .env 里的模型 Token。
echo ============================================================
echo.

echo [1/7] 抓取欧盟法规...
python scripts\fetch_eu.py || goto :err
echo [2/7] 抓取美国法规...
python scripts\fetch_us.py || goto :err
echo [3/7] 合并 + 体检（含去重）...
python scripts\merge_corpus.py || goto :err
echo [4/7] 链接实测（非破坏写入）...
python scripts\check_links.py || goto :err
echo [5/7] 批量补中文名...
python scripts\enrich_cn.py || goto :err
echo [6/7] 生成数据总览...
python scripts\make_overview.py || goto :err
echo [7/7] 生成欧盟待补清单...
python scripts\make_todo_eu.py || goto :err

echo.
echo   [OK] 管线跑完，data\ 下文件已全部刷新。
pause
exit /b 0

:err
echo.
echo   [X] 上一步失败，已中止。修复后重跑本脚本即可（中途产物可缓存复用）。
pause
exit /b 1
