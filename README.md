# Forward test: day-trader-skill (paper only)

ทดสอบกฎ "ทะลุกรอบ 15 นาทีแรก" ของ day-trader-skill กับราคาจริงทุกวัน **ไม่ส่งคำสั่งซื้อขายใดๆ ไม่ใช้ API key**

- รันเองทุกวันจันทร์-ศุกร์ 04:30 น. เวลาไทย (หลังตลาดสหรัฐปิด)
- ผลสรุปอยู่ที่ `SUMMARY.md` | รายละเอียดทุกไม้อยู่ที่ `results.csv`
- แก้รายชื่อหุ้นใน `symbols.txt`
- กดรันเองได้: แท็บ Actions → forward-test → Run workflow
- หยุด: แท็บ Actions → forward-test → ⋯ → Disable workflow

`trader-timemachine/timemachine.py` มาจาก github.com/Jakeschincariol/day-trader-skill (MIT, ดู LICENSE-day-trader-skill) ไม่ได้แก้ไข
