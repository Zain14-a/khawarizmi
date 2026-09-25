"""
نقطة دخول WSGI لاستضافة PythonAnywhere (ولأي خادم WSGI آخر).
لا تشغّل هذا الملف مباشرة — PythonAnywhere يستدعي التطبيق عبر هذا الملف
(يُستورد `application` من هنا).
"""
from app import app as application  # noqa: F401