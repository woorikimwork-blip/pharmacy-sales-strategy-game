# pharmacy-sales-strategy-game
더마화장품 오프라인 영업 전략 게임

## 약국 리스트 업데이트 방식

공공데이터 API 키는 `.env` 파일의 `PUBLIC_DATA_SERVICE_KEY`에만 저장합니다. `.env`는 Git에 올리지 않습니다.

1. 검토 리포트와 후보 파일 생성

```powershell
python update_pharmacy_data.py
```

생성 파일:
- `outputs/pharmacy_update_review.json`: 신규, 폐업 의심, 전화번호/좌표 변경 검토 리포트
- `outputs/pharmacy_data_candidate.js`: 실제 반영 전 후보 데이터

2. 리포트 검토

신규 약국 수, 폐업 의심 약국 수, 후보 총 약국 수를 먼저 확인합니다. 기본 실행은 `pharmacy_data.js`를 수정하지 않습니다.

3. 검토 후 반영

```powershell
python apply_update.py --yes
```

반영 전에 `outputs/pharmacy_data_backup_날짜시간.js` 백업이 자동 생성됩니다.

긴급히 한 번에 반영해야 할 때만 아래 명령을 사용할 수 있습니다.

```powershell
python update_pharmacy_data.py --apply
```
