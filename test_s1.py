from binance.client import Client
from datetime import datetime, timedelta
import re
import os
import traceback 
import sys
import pandas as pd
import pytz
from pathlib import Path
from s1 import pivot_data, detect_pivot, save_log, set_current_time_and_user

DEBUG_LOG_FILE = "debug_historical_test.log"

class S1HistoricalTester:
    def __init__(self, user_login="lenhat20791"):
        try:
            self.client = Client()
            self.debug_log_file = DEBUG_LOG_FILE
            self.user_login = user_login
            self.symbol = "BTCUSDT"           # Thêm symbol
            self.interval = "30m"             # Thêm interval
            self.clear_log_file()
            
            # Test kết nối
            self.client.ping()
            self.log_message("✅ Kết nối Binance thành công", "SUCCESS")
        except Exception as e:
            self.log_message(f"❌ Lỗi kết nối Binance: {str(e)}", "ERROR")
            raise
    
    def convert_to_vn_time(self, utc_time_str_or_dt):
        """Chuyển đổi thời gian từ UTC sang VN"""
        try:
            if isinstance(utc_time_str_or_dt, str):
                # Nếu là string format HH:MM
                if re.match(r'^\d{2}:\d{2}$', utc_time_str_or_dt):
                    utc_time = datetime.strptime(utc_time_str_or_dt, '%H:%M')
                    vn_time = utc_time + timedelta(hours=7)
                    return vn_time.strftime('%H:%M')
                    
                # Nếu là string format YYYY-MM-DD HH:MM:SS
                elif re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', utc_time_str_or_dt):
                    utc_dt = datetime.strptime(utc_time_str_or_dt, '%Y-%m-%d %H:%M:%S')
                    utc_dt = utc_dt.replace(tzinfo=pytz.UTC)
                    vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
                    vn_time = utc_dt.astimezone(vietnam_tz)
                    return vn_time
            elif isinstance(utc_time_str_or_dt, datetime):
                # Nếu là datetime object, giả sử là UTC
                utc_dt = utc_time_str_or_dt
                if utc_dt.tzinfo is None:
                    utc_dt = utc_dt.replace(tzinfo=pytz.UTC)
                vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
                vn_time = utc_dt.astimezone(vietnam_tz)
                return vn_time
                
            # Trường hợp khác, trả về nguyên giá trị
            return utc_time_str_or_dt
        except Exception as e:
            self.log_message(f"Lỗi chuyển đổi thời gian: {str(e)}", "ERROR")
            return utc_time_str_or_dt
    
    def clear_log_file(self):
        """Xóa nội dung của file log để bắt đầu test mới"""
        try:
            with open(self.debug_log_file, 'w', encoding='utf-8') as f:
                f.write('=== Log Initialized ===\n')
        except Exception as e:
            print(f"Error clearing log file: {str(e)}")

    def log_message(self, message, level="INFO"):
        """Ghi log ra console và file với level"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        formatted_message = f"[{timestamp}] [{level}] {message}"
        print(formatted_message)
        with open(self.debug_log_file, "a", encoding="utf-8") as f:
            f.write(f"{formatted_message}\n")
 
    def validate_data(self, df):
        """Kiểm tra dữ liệu trước khi xử lý"""
        if df.empty:
            raise ValueError("Không có dữ liệu")
            
        required_columns = ['datetime', 'time', 'high', 'low', 'price']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Thiếu các cột: {missing_columns}")
            
        # Kiểm tra giá trị hợp lệ
        if df['high'].min() <= 0 or df['low'].min() <= 0:
            raise ValueError("Phát hiện giá không hợp lệ (<=0)")
            
        # Kiểm tra high >= low
        if not (df['high'] >= df['low']).all():
            raise ValueError("Phát hiện high < low")
    
    def analyze_results(self, final_pivots, df):
        """Phân tích kết quả test chi tiết"""
        self.log_message("\n=== Phân tích kết quả ===", "SUMMARY")
        
        # Thống kê pivot
        pivot_types = {}
        for pivot in final_pivots:
            pivot_type = pivot['type']
            pivot_types[pivot_type] = pivot_types.get(pivot_type, 0) + 1
        
        # Log thống kê
        self.log_message(f"Tổng số nến: {len(df)}")
        self.log_message(f"Tổng số pivot: {len(final_pivots)}")
        
        # Chi tiết từng loại pivot
        for ptype in ['HH', 'HL', 'LH', 'LL']:
            count = pivot_types.get(ptype, 0)
            self.log_message(f"- {ptype}: {count}")
        
        # Thêm thống kê thời gian
        if final_pivots:
            time_diffs = []
            for i in range(1, len(final_pivots)):
                current = datetime.strptime(final_pivots[i]['time'], '%H:%M')
                previous = datetime.strptime(final_pivots[i-1]['time'], '%H:%M')
                diff = (current - previous).total_seconds() / 60  # Convert to minutes
                time_diffs.append(diff)
                
            if time_diffs:
                avg_time = sum(time_diffs) / len(time_diffs)
                self.log_message(f"\nThời gian trung bình giữa các pivot: {avg_time:.1f} phút")
    
    def save_test_results(self, df, results):
        """
        Lưu kết quả test vào Excel và vẽ biểu đồ
        
        Parameters:
        df (DataFrame): DataFrame chứa dữ liệu gốc với các cột datetime, vn_time, high, low, price
        results (list): Danh sách các pivot đã được xác nhận
        """
        try:
            # Lấy danh sách pivot từ pivot_data
            confirmed_pivots = pivot_data.confirmed_pivots.copy()
            
            # Tạo DataFrame mới cho các pivot
            pivot_records = []
            
            for pivot in confirmed_pivots:
                # Tìm bản ghi tương ứng trong df dựa trên vn_time
                matching_time = df[df['vn_time'] == pivot['time']]
                if not matching_time.empty:
                    pivot_records.append({
                        'datetime': matching_time['datetime'].iloc[0],
                        'price': pivot['price'],
                        'type': pivot['type'],
                        'time_vn': pivot['time'],
                        'date_vn': matching_time['vn_date'].iloc[0]
                    })

            # Chuyển list thành DataFrame và sắp xếp theo thời gian
            pivot_df = pd.DataFrame(pivot_records)
            if not pivot_df.empty:
                pivot_df = pivot_df.sort_values('datetime')
            
            # Tạo Excel file với xlsxwriter
            with pd.ExcelWriter('test_results.xlsx', engine='xlsxwriter') as writer:
                # Ghi vào sheet Pivot Analysis
                pivot_df.columns = ['Datetime (UTC)', 'Price', 'Pivot Type', 'Time (VN)', 'Date (VN)']
                pivot_df.to_excel(writer, sheet_name='Pivot Analysis', index=False)
                
                workbook = writer.book
                worksheet = writer.sheets['Pivot Analysis']
                
                # Định dạng cột
                date_format = workbook.add_format({
                    'num_format': 'yyyy-mm-dd hh:mm:ss',
                    'align': 'center'
                })
                price_format = workbook.add_format({
                    'num_format': '$#,##0.00',
                    'align': 'right'
                })
                header_format = workbook.add_format({
                    'bold': True,
                    'align': 'center',
                    'bg_color': '#D9D9D9'
                })
                
                # Thêm header cho Time (VN)
                worksheet.write(0, 3, 'Time (VN)', header_format)
                
                # Thêm công thức chuyển đổi múi giờ VN
                row_start = 1
                last_row = len(pivot_df)
                for row in range(row_start, last_row + 1):
                    formula = f'=A{row+1}+TIME(7,0,0)'
                    worksheet.write_formula(row, 3, formula, date_format)
                
                # Định dạng các cột
                worksheet.set_column('A:A', 20, date_format)    # datetime
                worksheet.set_column('B:B', 15, price_format)   # price
                worksheet.set_column('C:C', 12)                 # pivot_type
                worksheet.set_column('D:D', 10)                 # time_vn
                worksheet.set_column('E:E', 12)                 # date_vn

                # Thêm công thức chuyển đổi múi giờ cho cột Time (VN)
                for row in range(1, len(pivot_df) + 1):
                    formula = f'=A{row+1}+TIME(7,0,0)'
                    worksheet.write_formula(row, 3, formula, date_format)
                    
                # Thêm thống kê
                stats_row = len(pivot_df) + 3
                stats_format = workbook.add_format({
                    'bold': True,
                    'bg_color': '#E6E6E6'
                })
                
                # Viết phần thống kê
                worksheet.write(stats_row, 0, "Thống kê:", stats_format)
                worksheet.write(stats_row + 1, 0, "Tổng số pivot:")
                worksheet.write(stats_row + 1, 1, len(pivot_df), price_format)
                
                # Thống kê theo loại pivot
                pivot_counts = pivot_df['Pivot Type'].value_counts() if not pivot_df.empty else pd.Series()
                worksheet.write(stats_row + 2, 0, "Phân bố pivot:", stats_format)
                
                row = stats_row + 3
                for pivot_type in ['HH', 'HL', 'LH', 'LL']:
                    count = pivot_counts.get(pivot_type, 0)
                    worksheet.write(row, 0, f"{pivot_type}:")
                    worksheet.write(row, 1, count)
                    row += 1
                
                # Tạo biểu đồ
                chart = workbook.add_chart({'type': 'scatter'})
                
                if not pivot_df.empty:
                    # Thêm series cho price
                    chart.add_series({
                        'name': 'Pivot Points',
                        'categories': f"='Pivot Analysis'!$A$2:$A${len(pivot_df) + 1}",  # Thêm dấu nháy đơn
                        'values': f"='Pivot Analysis'!$B$2:$B${len(pivot_df) + 1}",      # Thêm dấu nháy đơn
                        'marker': {
                            'type': 'circle',
                            'size': 8,
                            'fill': {'color': '#FF4B4B'},
                            'border': {'color': '#FF4B4B'}
                        },
                        'line': {'none': True}
                    })
                
                # Định dạng biểu đồ
                chart.set_title({
                    'name': 'Pivot Points Analysis (Vietnam Time)',
                    'name_font': {'size': 14, 'bold': True}
                })
                
                chart.set_x_axis({
                    'name': 'Time (Vietnam)',
                    'num_format': 'dd/mm/yyyy\nhh:mm',
                    'label_position': 'low',
                    'major_unit': 1,
                    'major_unit_type': 'days',
                    'line': {'color': '#CCCCCC'},
                    'major_gridlines': {'visible': True, 'line': {'color': '#CCCCCC'}}
                })
                
                chart.set_y_axis({
                    'name': 'Price',
                    'num_format': '$#,##0',
                    'line': {'color': '#CCCCCC'},
                    'major_gridlines': {'visible': True, 'line': {'color': '#CCCCCC'}}
                })
                
                chart.set_legend({'position': 'bottom'})
                chart.set_size({'width': 920, 'height': 600})
                
                # Chèn biểu đồ vào worksheet
                worksheet.insert_chart('E2', chart)
                
                # Thêm sheet Data để lưu dữ liệu gốc - Chỉ lưu dữ liệu với thời gian VN
                df_to_save = df[['datetime', 'vn_time', 'high', 'low', 'price']].copy()
                # Đổi tên cột cho rõ ràng
                df_to_save = df_to_save.rename(columns={'vn_time': 'time_vn'})
                df_to_save.to_excel(writer, sheet_name='Raw Data', index=False)
                
                # Định dạng sheet Data
                worksheet_data = writer.sheets['Raw Data']
                worksheet_data.set_column('A:A', 20, date_format)  # datetime
                worksheet_data.set_column('B:B', 10)               # time_vn
                worksheet_data.set_column('C:E', 15, price_format) # high, low, price
                
                # Thêm tiêu đề cột rõ ràng hơn
                for col_num, value in enumerate(['Datetime (VN)', 'Time (VN)', 'High', 'Low', 'Price']):
                    worksheet_data.write(0, col_num, value, header_format)
                
                # Log kết quả
                self.log_message("\nĐã lưu kết quả test vào file test_results.xlsx", "SUCCESS")
                self.log_message(f"Tổng số pivot: {len(pivot_df)}", "INFO")
                self.log_message("Phân bố pivot:", "INFO")
                for pivot_type in ['HH', 'HL', 'LH', 'LL']:
                    count = pivot_counts.get(pivot_type, 0)
                    self.log_message(f"- {pivot_type}: {count}", "INFO")
                
                return True
                
        except Exception as e:
            self.log_message(f"Lỗi khi lưu Excel: {str(e)}", "ERROR")
            self.log_message(traceback.format_exc(), "ERROR")
            return False

    def run_test(self):
        """Chạy historical test cho S1"""
        try:
            # Thời gian bắt đầu: 00:00 15/03 VN = 17:00 14/03 UTC
            start_time = datetime(2025, 3, 14, 17, 0, 0)
            start_time_vn = (start_time + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')
            
            # Thời gian kết thúc: 19:00 16/03 VN = 12:00 15/03 UTC
            end_time = datetime(2025, 3, 16, 12, 0, 0)  
            end_time_vn = (end_time + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')
                
            self.log_message("\n=== Bắt đầu test S1 ===", "INFO")
            self.log_message(f"Symbol: {self.symbol}", "INFO")
            self.log_message(f"Interval: {self.interval}", "INFO")
            self.log_message(f"User: {self.user_login}", "INFO")
            self.log_message(f"Thời gian bắt đầu (Vietnam): {start_time_vn}", "INFO")
            self.log_message(f"Thời gian kết thúc (Vietnam): {end_time_vn}", "INFO")
            self.log_message(f"Thời gian bắt đầu (UTC): {start_time.strftime('%Y-%m-%d %H:%M:%S')}", "INFO")
            self.log_message(f"Thời gian kết thúc (UTC): {end_time.strftime('%Y-%m-%d %H:%M:%S')}", "INFO")
                
            # Lấy dữ liệu từ Binance
            klines = self.client.get_historical_klines(
                self.symbol,
                Client.KLINE_INTERVAL_30MINUTE,
                start_str=int(start_time.timestamp() * 1000),
                end_str=int(end_time.timestamp() * 1000)
            )
                
            if not klines:
                self.log_message("Không tìm thấy dữ liệu cho khoảng thời gian này", "ERROR")
                return None

            # Chuyển đổi dữ liệu thành DataFrame
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 
                'volume', 'close_time', 'quote_volume', 'trades',
                'buy_base_volume', 'buy_quote_volume', 'ignore'
            ])

            # Xử lý timestamp và timezone
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')

            # Lưu thời gian UTC để theo dõi
            df['utc_time'] = df['datetime'].dt.strftime('%H:%M')
            df['utc_date'] = df['datetime'].dt.strftime('%Y-%m-%d')

            # Chuyển sang múi giờ Việt Nam
            df['datetime'] = df['datetime'].dt.tz_convert(vietnam_tz)

            # Lưu thời gian Việt Nam
            df['vn_time'] = df['datetime'].dt.strftime('%H:%M')
            df['vn_date'] = df['datetime'].dt.strftime('%Y-%m-%d')
            df['vn_date_time'] = df['datetime'].dt.strftime('%Y-%m-%d %H:%M')

            # Loại bỏ timezone để tránh vấn đề với Excel
            df['datetime'] = df['datetime'].dt.tz_localize(None)

            # Ghi log so sánh thời gian
            self.log_message("\n=== Chuyển đổi múi giờ ===", "INFO")
            self.log_message("| UTC Date | UTC Time | Vietnam Date | Vietnam Time |", "INFO")
            self.log_message("|----------|----------|--------------|--------------|", "INFO")
            for idx, row in df.head(5).iterrows():  # Hiển thị 5 hàng đầu tiên
                self.log_message(f"| {row['utc_date']} | {row['utc_time']} | {row['vn_date']} | {row['vn_time']} |", "INFO")

            # Chọn và format dữ liệu cần thiết
            df = df[['datetime', 'utc_time', 'utc_date', 'vn_time', 'vn_date', 'vn_date_time', 'high', 'low', 'close']]
            df = df.rename(columns={'close': 'price'})
            for col in ['high', 'low', 'price']:
                df[col] = df[col].astype(float)
                
            self.log_message(f"\nTổng số nến: {len(df)}", "INFO")
                
            # Reset S1
            pivot_data.clear_all()
                
            # Đảm bảo initial pivots sử dụng giờ Việt Nam
            initial_pivots = [
                {
                    'type': 'LL',
                    'price': 79894.0,
                    'vn_time': '00:30',
                    'vn_date': '2025-03-14',
                    'direction': 'low',
                    'confirmed': True
                },
                {
                    'type': 'LH',
                    'price': 82266.0,
                    'vn_time': '09:30',
                    'vn_date': '2025-03-14',
                    'direction': 'high',
                    'confirmed': True
                },
                {
                    'type': 'HL',
                    'price': 81730.0,
                    'vn_time': '13:30',
                    'vn_date': '2025-03-14',
                    'direction': 'low',
                    'confirmed': True
                },
                {
                    'type': 'HH',
                    'price': 85270.0,
                    'vn_time': '22:30',
                    'vn_date': '2025-03-14',
                    'direction': 'high',
                    'confirmed': True
                }
]

            # Ghi log xác nhận pivot ban đầu
            self.log_message("\n=== Đã thêm pivot ban đầu từ Trading View ===", "INFO")
            self.log_message("(Đây là thời gian theo múi giờ Việt Nam GMT+7)", "INFO")
            self.log_message(f"Tổng số pivot khởi tạo: {len(initial_pivots)}", "INFO")

            # Thêm phương thức add_initial_trading_view_pivots vào PivotData để xử lý đúng múi giờ
            if hasattr(pivot_data, 'add_initial_trading_view_pivots'):
                # Sử dụng phương thức mới nếu có
                pivot_data.add_initial_trading_view_pivots(initial_pivots)
                
                # Log các pivot đã thêm
                for pivot in initial_pivots:
                    vn_datetime = f"{pivot['vn_date']} {pivot['vn_time']}"
                    self.log_message(f"- {pivot['type']} tại ${pivot['price']:,.2f} (VN: {vn_datetime})", "INFO")
            else:
                # Fallback nếu không có phương thức mới
                self.log_message("⚠️ WARNING: Không tìm thấy phương thức add_initial_trading_view_pivots", "WARNING")
                self.log_message("⚠️ Thêm pivot theo cách thủ công và chuyển đổi múi giờ", "WARNING")
                
                pivot_data.confirmed_pivots.clear()  # Xóa toàn bộ pivot hiện có
                
                for pivot in initial_pivots:
                    # Chuyển đổi thời gian Việt Nam sang UTC
                    vn_datetime = f"{pivot['vn_date']} {pivot['vn_time']}"
                    vn_dt = datetime.strptime(vn_datetime, '%Y-%m-%d %H:%M')
                    utc_dt = vn_dt - timedelta(hours=7)
                    
                    # Tạo pivot với thời gian UTC
                    utc_pivot = pivot.copy()
                    utc_pivot['time'] = utc_dt.strftime('%H:%M')  # Thời gian UTC
                    utc_pivot['utc_date'] = utc_dt.strftime('%Y-%m-%d')
                    utc_pivot['utc_datetime'] = utc_dt.strftime('%Y-%m-%d %H:%M')
                    utc_pivot['vn_datetime'] = vn_datetime
                    utc_pivot['skip_spacing_check'] = True
                    
                    # Thêm pivot vào S1
                    pivot_data.confirmed_pivots.append(utc_pivot)
                    
                    # Log pivot đã thêm
                    self.log_message(f"- {pivot['type']} tại ${pivot['price']:,.2f} (VN: {vn_datetime}, UTC: {utc_pivot['utc_datetime']})", "INFO")

            # Cung cấp dữ liệu cho S1
            self.log_message("\nBắt đầu cung cấp dữ liệu cho S1...", "INFO")

            # Thêm biến để theo dõi thời điểm log cuối
            last_log_time = None
            log_interval = timedelta(minutes=30)  # Log mỗi 30 phút
            
            for index, row in df.iterrows():
                current_time = row['datetime']
                
                # Chỉ log nếu đã đủ interval hoặc có biến động lớn
                significant_change = abs(row['high'] - row['low']) > 100  # Biến động >$100
                should_log = (
                    last_log_time is None or 
                    (current_time - last_log_time) >= log_interval or
                    significant_change
                )
                
                if should_log:
                    # Nếu là 17:00 14/03, hiển thị (00:00 15/03/2025)
                    vn_hour, vn_minute = map(int, row['vn_time'].split(':'))
                    vn_date_obj = datetime.strptime(row['vn_date'], '%Y-%m-%d')
                    
                    # Nếu là buổi tối (17:00-23:59), hiển thị sáng hôm sau
                    if vn_hour >= 17:
                        reference_date = vn_date_obj + timedelta(days=1)
                        reference_hour = vn_hour - 17
                        reference_time = f"{reference_hour:02d}:{vn_minute:02d}"
                    # Nếu là sáng sớm (00:00-07:00), hiển thị tối hôm trước 
                    elif vn_hour < 7:
                        reference_date = vn_date_obj
                        reference_hour = vn_hour + 17
                        reference_time = f"{reference_hour:02d}:{vn_minute:02d}"
                        reference_date = reference_date - timedelta(days=1)
                    # Trường hợp còn lại (07:00-16:59)
                    else:
                        reference_date = vn_date_obj
                        reference_hour = vn_hour - 7
                        reference_time = f"{reference_hour:02d}:{vn_minute:02d}"
                    
                    reference_date_str = reference_date.strftime("%d/%m/%Y")
                    
                    # Hiển thị log với format bạn yêu cầu
                    self.log_message(f"\n=== Nến {row['utc_date']} {row['utc_time']} ({row['utc_date']} {row['utc_time']} UTC) ===", "DETAIL")
                    self.log_message(f"Giá: ${row['price']:,.2f}")
                    if significant_change:
                        self.log_message(f"⚠️ Biến động lớn: ${row['high']:,.2f} - ${row['low']:,.2f}")
                    last_log_time = current_time
                
                # Cung cấp dữ liệu cho S1
                price_data = {
                    'time': row['vn_time'],       # Thời gian Việt Nam
                    'vn_time': row['vn_time'],    # Đánh dấu rõ là thời gian Việt Nam
                    'price': row['price'],
                    'high': row['high'],
                    'low': row['low'],
                    'vn_date': row['vn_date']     # Đánh dấu rõ là ngày Việt Nam
                }
                # Thay đổi từ add_price_data sang process_new_data
                pivot_data.process_new_data(price_data)
                
            # Lấy kết quả từ S1
            final_pivots = pivot_data.get_all_pivots()  # Sử dụng get_all_pivots để lấy pivot đã format
                
            # Log kết quả cuối cùng
            self.log_message("\n=== Kết quả test S1 ===", "SUMMARY")
            self.log_message(f"Tổng số nến đã xử lý: {len(df)}")
            self.log_message(f"Tổng số pivot được S1 xác nhận: {len(final_pivots)}")

            if final_pivots:
                self.log_message("\nDanh sách pivot S1 đã xác nhận:")
                for pivot in final_pivots:
                    # Log với thời gian Việt Nam nhất quán
                    if 'vn_datetime' in pivot:
                        self.log_message(f"- {pivot['type']} tại ${pivot['price']:,.2f} (VN: {pivot['vn_datetime']})")
                    elif 'utc_datetime' in pivot:
                        # Chuyển từ UTC sang VN để hiển thị
                        try:
                            utc_dt = datetime.strptime(pivot['utc_datetime'], '%Y-%m-%d %H:%M')
                            vn_dt = utc_dt + timedelta(hours=7)
                            vn_datetime = vn_dt.strftime('%Y-%m-%d %H:%M')
                            self.log_message(f"- {pivot['type']} tại ${pivot['price']:,.2f} (VN: {vn_datetime}, UTC: {pivot['utc_datetime']})")
                        except:
                            self.log_message(f"- {pivot['type']} tại ${pivot['price']:,.2f} (UTC: {pivot['utc_datetime']})")
                    else:
                        # Fallback
                        self.log_message(f"- {pivot['type']} tại ${pivot['price']:,.2f} ({pivot.get('time', 'unknown time')})")                        
            # Lưu kết quả vào Excel
            self.save_test_results(df, final_pivots)
                
            return final_pivots
                
        except Exception as e:
            self.log_message(f"❌ Lỗi khi chạy test: {str(e)}", "ERROR")
            self.log_message(traceback.format_exc(), "ERROR")
            return None
            
def main():
    try:
        # Lấy thời gian hiện tại từ tham số hoặc biến môi trường
        if len(sys.argv) > 1:
            utc_time = sys.argv[1]  # Lấy từ command line 
        else:
            # Lấy từ biến môi trường nếu có
            utc_time = os.environ.get('CURRENT_UTC_TIME')
            
            # Nếu không có, sử dụng thời gian được cung cấp
            if not utc_time:
                utc_time = "2025-03-21 02:40:48"   # Thời gian từ prompt
        
        # Chuyển sang múi giờ Việt Nam (+7)
        utc = pytz.UTC
        vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        utc_dt = datetime.strptime(utc_time, '%Y-%m-%d %H:%M:%S').replace(tzinfo=utc)
        vietnam_time = utc_dt.astimezone(vietnam_tz)
        
        # Format thời gian VN
        current_time = vietnam_time.strftime('%Y-%m-%d %H:%M:%S')
        save_log(f"\n=== Thông tin thời gian ===", DEBUG_LOG_FILE)
        save_log(f"UTC time: {utc_time}", DEBUG_LOG_FILE)
        save_log(f"Vietnam time: {current_time} (GMT+7)", DEBUG_LOG_FILE)
        
        # Lấy username từ tham số hoặc biến môi trường
        current_user = os.environ.get('CURRENT_USER', 'lenhat20791')
        
        print(f"Current Date and Time (UTC): {utc_time}")
        print(f"Current User's Login: {current_user}")
        
        # Cung cấp thông tin môi trường cho S1
        set_current_time_and_user(current_time, current_user)
        
        # Chạy test
        tester = S1HistoricalTester(current_user)
        print("Đang chạy historical test cho S1...")
        results = tester.run_test()
        
        print("\nTest hoàn tất! Kiểm tra file debug_historical_test.log và test_results.xlsx để xem chi tiết.")
        return results
        
    except Exception as e:
        print(f"Lỗi: {str(e)}")
        print(traceback.format_exc())
        return None
if __name__ == "__main__":
    main()
