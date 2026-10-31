@echo off
setlocal enabledelayedexpansion

call env\Scripts\activate

set DATA_PROFILE=prod

set TARGET=50000
set MIN_GROWTH=10
set PREV_LINES=0
set ROUND=0

echo [%date% %time%] BAT DAU PIPELINE > pipeline_status.txt

:crawl_loop
set /a ROUND+=1
echo.
echo ===================================================
echo Vong crawl thu %ROUND% (muc tieu: %TARGET% bai)
echo ===================================================
echo [%date% %time%] Vong crawl %ROUND% bat dau >> pipeline_status.txt

cd wiki_bot
call scrapy crawl wiki_spider --logfile ..\crawl_log.txt
cd ..

if not exist data\raw\wiki_crawler_dataset.jsonl (
    echo [LOI] Crawl khong tao ra file du lieu. Dung pipeline.
    echo [%date% %time%] LOI: khong co file du lieu >> pipeline_status.txt
    exit /b 1
)

for /f %%A in ('find /c /v "" ^< data\raw\wiki_crawler_dataset.jsonl') do set LINES=%%A
set /a DELTA=LINES-PREV_LINES
echo Hien co khoang %LINES% bai viet (them %DELTA% bai trong vong nay).
echo [%date% %time%] Vong %ROUND% xong: %LINES% bai (+%DELTA%) >> pipeline_status.txt

if %LINES% GEQ %TARGET% goto embed

if %DELTA% LSS %MIN_GROWTH% (
    echo Vong nay chi them %DELTA% bai - coi nhu da het nguon trong pham vi depth.
    echo Chap nhan %LINES% bai va chuyen sang embedding.
    echo [%date% %time%] Frontier can tai %LINES% bai >> pipeline_status.txt
    goto embed
)

set PREV_LINES=%LINES%
goto crawl_loop

:embed
echo.
echo ===================================================
echo Khu trung lap dataset truoc khi embedding
echo ===================================================
python dedupe_dataset.py
for /f %%A in ('find /c /v "" ^< data\raw\wiki_crawler_dataset.jsonl') do set LINES=%%A

echo.
echo ===================================================
echo Build vector database (profile: %DATA_PROFILE%)
echo ===================================================
echo [%date% %time%] Bat dau embedding voi %LINES% bai >> pipeline_status.txt
python -m src.indexing.build_vector_db
if errorlevel 1 (
    echo [%date% %time%] LOI khi build vector DB >> pipeline_status.txt
    exit /b 1
)

echo.
echo ===================================================
echo HOAN TAT: %LINES% bai da duoc crawl va embedding
echo ===================================================
echo [%date% %time%] HOAN TAT PIPELINE: %LINES% bai >> pipeline_status.txt
endlocal
