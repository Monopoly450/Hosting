import re

with open("backend/app/core/k8s_client.py", "r") as f:
    content = f.read()

# Replace IP collecting logic
parse_old = """        elif vmi:
            status = vmi.get("status", {}).get("phase", "Unknown")
            node_name = vmi.get("status", {}).get("nodeName", "")
            
            # Собираем IP адреса
            interfaces = vmi.get("status", {}).get("interfaces", [])
            for iface in interfaces:
                ip = iface.get("ipAddress")
                if ip:
                    ips.append(ip)
                for ip_addr in iface.get("ipAddresses", []):
                    if ip_addr not in ips:
                        ips.append(ip_addr)
        else:"""

parse_new = """        elif vmi:
            status = vmi.get("status", {}).get("phase", "Unknown")
            node_name = vmi.get("status", {}).get("nodeName", "")
            
            # Собираем IP адреса
            interfaces = vmi.get("status", {}).get("interfaces", [])
            for iface in interfaces:
                ip = iface.get("ipAddress")
                if ip:
                    ips.append(ip)
                for ip_addr in iface.get("ipAddresses", []):
                    if ip_addr not in ips:
                        ips.append(ip_addr)
                        
            # Сохраняем IP в аннотацию, чтобы помнить его после выключения
            if ips:
                main_ip = ips[0]
                annotations = vm.get("metadata", {}).get("annotations", {})
                last_ip = annotations.get("hosting.antigravity.io/last-ip")
                if main_ip != last_ip:
                    try:
                        patch = {"metadata": {"annotations": {"hosting.antigravity.io/last-ip": main_ip}}}
                        self.custom_api.patch_namespaced_custom_object(
                            "kubevirt.io", "v1", "default", "virtualmachines", name, patch
                        )
                    except Exception as e:
                        logger.error(f"Failed to save last-ip for {name}: {e}")
        else:"""

content = content.replace(parse_old, parse_new)

# Add fallback to annotation if ips is empty
fallback_old = """        # Шаблон ОС
        os_type = vm["metadata"].get("labels", {}).get("hosting.antigravity.io/template", "unknown")"""

fallback_new = """        # Если машина выключена и ips пуст, берем из аннотации
        if not ips:
            last_ip = vm.get("metadata", {}).get("annotations", {}).get("hosting.antigravity.io/last-ip")
            if last_ip:
                ips.append(last_ip)

        # Шаблон ОС
        os_type = vm["metadata"].get("labels", {}).get("hosting.antigravity.io/template", "unknown")"""

content = content.replace(fallback_old, fallback_new)

with open("backend/app/core/k8s_client.py", "w") as f:
    f.write(content)
