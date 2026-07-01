import sys
sys.path.append('.')
from app.core.k8s_client import K8sClient
try:
    c = K8sClient()
    print(c.get_vm("fbff"))
except Exception as e:
    print(e)
