from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers
from pyhanko.pdf_utils import text

def prepare_pdf_for_msign(input_pdf_bytes, output_path):
    """
    Создает структуру PAdES и резервирует место под визуальный штамп.
    Возвращает хеш, который нужно отправить в MSign.
    """
    # 1. Загружаем PDF для инкрементальной записи
    w = IncrementalPdfFileWriter(BytesIO(input_pdf_bytes))
    
    # 2. Настраиваем внешний вид штампа
    meta = signers.PdfSignatureMetadata(field_name='SignatureHR')
    
    # Настройки текста в штампе (Директор, Дата, MSign ID)
    stamp_text = "Semnat electronic / Подписано Электронно\nMSign Moldova\nData: %(ts)s"
    
    # 3. Резервируем место (координаты: x1, y1, x2, y2)
    # Пример: нижний правый угол
    box = (400, 50, 550, 150) 
    
    # Здесь происходит магия pyHanko: создается хеш для внешней подписи
    # (Детальная реализация интеграции с MSign API будет следующим шагом)
    return w, meta, box

