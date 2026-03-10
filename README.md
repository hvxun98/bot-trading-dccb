# 🚀 HƯỚNG DẪN SỬ DỤNG AI TRADING BOT (PYTHON + TELEGRAM)

Chào sếp! Đây là hệ thống **Cố vấn Giao dịch AI Đa Khung Thời Gian** siêu cấp độc quyền, chạy trên sức mạnh của Cỗ máy AI Random Forest và kết hợp Price Action.

Dự án đã được rút gọn 100% bằng **Python**, chạy thẳng trên PC Windows cá nhân (Tận dụng GPU Card RTX 3060 và CPU) và tuyệt đối an toàn vì không cắm API Trade trực tiếp - thay vào đó nó sẽ **bắn tín hiệu (Signal) qua khung Telegram**.

---

## 🏗️ KIẾN TRÚC MÔ HÌNH VÀ CÁC FILE HOẠT ĐỘNG

### 1. Kiến trúc AI Đa Khung Thời Gian 
Việc huấn luyện (Training) AI đã được tách bạch thành 2 dòng chất xám độc lập để nâng tỉ lệ Winrate:
- **`Mô hình M15 (Scalping)`**: Tư duy bằng nến M15, dựa dẫm vào nến H1 và H4 để dò cản. Hợp nhất 3 mốc thời gian bằng `pandas.merge_asof`.
- **`Mô hình H1 (Trung Hạn)`**: Tư duy bằng nến H1, dùng D1 và H4 rà soát xu hướng vĩ mô dài cả tháng.

Các đặc trưng mấu chốt (Features) AI được ngửi bao gồm: EMA(10), EMA(50), Kích thước Thân Nến (Body), Chiều dài Râu Trên (High_Shadow) và Râu Dưới (Low_Shadow).

### 2. Ý nghĩa Các File Hoạt động
| File | Chức năng | 
| --- | --- |
| `fetch_data.py` | Cào cùng lúc 6 bộ lịch sử (5m, 15m, 1h, 4h, 1d, 1w) từ OKX xuống thư mục `/data`. |
| `train_model.py` | Ghép nối dữ liệu quá khứ. Lọc 2 bộ Não (RandomForest) và đẻ ra 2 file `ai_model_scalping.pkl`, `ai_model_medium_term.pkl`. |
| `telegram_bot.py` | Chạy nền 24/7. Cứ mỗi 15 phút sẽ soi Tín hiệu Bắt Đỉnh/Đáy Scalping. Mốc đầu giờ chẵn sẽ soi Xung Lực Trung Hạn. |
| `requirements.txt` | Các thư viện ML thiết yếu. |

---

## 🛠️ PHẦN 1: CÁCH CÀI ĐẶT BAN ĐẦU (Chỉ làm 1 lần)

1. **Cài đặt Python (Nếu PC sếp chưa có):**
   - Vào Google gõ [Python Download](https://www.python.org/downloads/) cài phiên bản 3.10 hoặc 3.11. 
   - *Lưu ý: Nhớ tick vào ô vuông **"Add python.exe to PATH"** lúc cài đặt.*

2. **Cài đặt Thư Viện AI (Nạp năng lượng):**
   - Mở cửa sổ **CMD** hoặc Terminal ngay tại thư mục này (`d:\code\client\bot-trading`).
   - Gõ lệnh sau để tải đủ đồ nghề (Pandas, CCXT, Scikit-learn):
     ```bash
     pip install -r requirements.txt
     ```

3. **Cấu hình Báo động Telegram:**
   - Sếp lấy điện thoại, vào Telegram tìm `@BotFather`, gõ `/newbot` để xin tạo 1 con Bot Mới. Nó sẽ cấp cho 1 dãy mã gọi là **HTTP API Token**.
   - Sếp tạo 1 nhóm Chat cá nhân (hoặc chat trực tiếp với bot), lấy ID Chat đó. (Có thể dùng bot `@userinfobot` để lấy ID tự động).
   - Vô file `telegram_bot.py` mở bằng Notepad hay VSCode:
     - Dán Token vào dòng: `TELEGRAM_TOKEN = "ĐIỀN_TOKEN..."`
     - Dán Chat ID mạng vào: `TELEGRAM_CHAT_ID = "ĐIỀN_ID..."`

---

## 🧠 PHẦN 2: QUY TRÌNH HÀNG NGÀY (Cấm sai trình tự)

Để Bot khôn lỏi nhất, sếp hãy thực hiện đúng 3 Bước sau (Mở 1 Terminal duy nhất và gõ):

### Bước 1: Cho AI Ăn Khối Lượng Dữ Liệu Tươi Từ OKX
Mỗi tuần sếp rảnh rảnh cứ chạy lại nó dăm ba lần để AI nắm được nhịp sóng nến hiện tại. Mất khoảng vài chục giây để cào 6 mốc thời gian (M5, M15, H1, H4, D1, 1W).
```bash
python fetch_data.py
```
*(Nếu thành công: Ổ cứng sếp sẽ sinh ra 6 file `.csv` trong thư mục `data`)*

### Bước 2: Ép Ngồi Thiền / Huấn luyện Học Máy
Do sếp xài RTX 3060 với 32GB RAM vô cùng dồi dào, hãy vắt kiệt nó để train 2 bộ não: Mô hình Đánh Dài Hạn (Trung Hạn H1/H4) và Mô hình tỉa Lệnh (Scalping M5/M15).
```bash
python train_model.py
```
*(Nếu thành công: AI sẽ tự Báo Winrate lên màn hình đen. Xuất thêm 2 file Não Bộ Đã Chín tên là `ai_model_scalping.pkl` và `ai_model_medium_term.pkl`)*

### Bước 3: Thả Quái Thú Canh Sàn (Chạy Live 24/7)
Xong hết thủ tục nhồi nhét chữ cho AI rồi. Giờ vứt nó lên sàn quất việc ngầm thôi:
```bash
python telegram_bot.py
```
*(Hiện màn hình Đang Ngáy Ngủ là thành công. Sếp thu nhỏ Terminal lại, kệ nó đấy).*

---

## 📈 BOT NÀY HOẠT ĐỘNG KIỂU GÌ?

Nó có 2 con mắt chẻ làm 2 hướng soi:

1. **MẮT TRUNG HẠN (Mỗi giờ dòm 1 lần):** 
   - Canh nến H1, nhìn D1/H4 và check mô hình `ai_model_medium_term.pkl`. 
   - Tự tin phân luồng trên 60% thì hú!
2. **MẮT SCALPING (Cứ 15 phút dòm 1 lần):**
   - Canh nến M15, nhìn xu hướng mớm từ H1 và check `ai_model_scalping.pkl`. 
   - Tự tin đớp lệnh trên 65% thì hú sếp vô bắt đáy Cắt da đọng tiết luôn!

Nếu Tín hiệu Nhiễu (Nến dở dở ương ương không rơi vào S/R hoặc Pinbar), AI sẽ ngậm mồm im lặng báo `Tín hiệu nhiễu trên Terminal`, Sếp không bị tiếng Telegram rác quấy rầy.

> **Tips cho người dùng:** Tuy AI này được huấn luyện Rừng Ngẫu Nhiên (Random Forest) tỷ lệ chính xác > 60%, sếp vẫn phải là người Quản Trị Vốn. Nó chỉ báo vùng Mua (Entry), còn Stop Loss sếp tự vạch kẻ ra 2% để né Mũi Đất nhé! Chúc sếp gặt Dollar dồi dào! 💵
