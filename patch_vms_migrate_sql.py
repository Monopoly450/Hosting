import re

with open("backend/app/api/vms.py", "r") as f:
    content = f.read()

# Replace the incorrect db code with proper SQLAlchemy logic
old_func_start = """@router.post("/{name}/migrate")
def migrate_vm(name: str, target_server_id: str = Query(...), k8s: K8sClient = Depends(get_k8s_client)):
    # 1. Получаем внешний сервер
    from app.api.external_servers import db as ext_db
    target_server = next((s for s in ext_db.get_all() if s.id == target_server_id), None)
    if not target_server:
        raise HTTPException(status_code=404, detail="Внешний сервер не найден")"""

new_func_start = """@router.post("/{name}/migrate")
async def migrate_vm(name: str, target_server_id: str, k8s: K8sClient = Depends(get_k8s_client), db: AsyncSession = Depends(get_db)):
    from app.models.models import ExternalServer
    from sqlalchemy import select
    
    res = await db.execute(select(ExternalServer).filter_by(id=target_server_id))
    target_server = res.scalars().first()
    
    if not target_server:
        raise HTTPException(status_code=404, detail="Внешний сервер не найден")"""

old_func_end = """    # 10. Регистрируем перенесенную ВМ как новый Внешний Сервер
    from app.api.external_servers import ExternalServer
    import uuid
    new_server = ExternalServer(
        id=str(uuid.uuid4()),
        name=f"{name} (Migrated)",
        ip=target_server.ip,
        port=ext_ssh_port,
        username=vm_user,
        password=vm_pass
    )
    ext_db.add_server(new_server)
    
    return {"status": "success", "message": f"ВМ {name} успешно мигрирована", "new_server_id": new_server.id}"""

new_func_end = """    # 10. Регистрируем перенесенную ВМ как новый Внешний Сервер
    from app.models.models import ExternalServer
    import uuid
    new_id = str(uuid.uuid4())[:8]
    new_server = ExternalServer(
        id=new_id,
        name=f"{name} (Migrated)",
        host=target_server.host,
        port=ext_ssh_port,
        username=vm_user,
        password=vm_pass
    )
    db.add(new_server)
    await db.commit()
    
    return {"status": "success", "message": f"ВМ {name} успешно мигрирована", "new_server_id": new_server.id}"""

# Fix target_server.ip -> target_server.host inside SSH block
old_ssh_block1 = """        ssh.connect(
            target_server.ip, 
            port=target_server.port,"""
new_ssh_block1 = """        ssh.connect(
            target_server.host, 
            port=target_server.port,"""

old_ssh_block2 = """scp_cmd = f"scp -o StrictHostKeyChecking=no -i {key_path} {disk_path} {target_server.username}@{target_server.ip}:/opt/antigravity/vms/{name}/disk.img\""""
new_ssh_block2 = """scp_cmd = f"scp -o StrictHostKeyChecking=no -i {key_path} {disk_path} {target_server.username}@{target_server.host}:/opt/antigravity/vms/{name}/disk.img\""""


content = content.replace(old_func_start, new_func_start)
content = content.replace(old_func_end, new_func_end)
content = content.replace(old_ssh_block1, new_ssh_block1)
content = content.replace(old_ssh_block2, new_ssh_block2)

# Ensure AsyncSession and get_db are imported at the top if not already
if "from sqlalchemy.ext.asyncio import AsyncSession" not in content:
    content = "from sqlalchemy.ext.asyncio import AsyncSession\nfrom app.core.database import get_db\n" + content

with open("backend/app/api/vms.py", "w") as f:
    f.write(content)
