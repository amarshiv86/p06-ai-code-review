import pytest


@pytest.fixture
def sample_diff():
    return """diff --git a/main.py b/main.py
index 0000000..1111111 100644
--- a/main.py
+++ b/main.py
@@ -1,5 +1,8 @@
+import os
 def hello():
-    password = "secret123"
+    password = os.getenv("PASSWORD")
     print(f"Hello {password}")
"""
