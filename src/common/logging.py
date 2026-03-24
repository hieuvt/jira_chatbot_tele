"""Cấu hình logging đơn giản cho toàn ứng dụng."""

import logging


def get_logger(name: str) -> logging.Logger:
    """Trả về logger tên `name`; lần đầu gọi sẽ basicConfig (INFO, format chuẩn)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return logging.getLogger(name)
