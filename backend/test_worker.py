import sys
import traceback
try:
    import app.worker
    print("Worker imported successfully!")
except Exception as e:
    print("Worker import failed!")
    traceback.print_exc()
