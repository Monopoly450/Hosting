import React, { useState, useEffect } from 'react';
import { 
  Cloud, Server, Shield, Database, Key, Plus, Trash2, 
  Check, X, RefreshCw, HelpCircle, ArrowRight, Lock, Unlock, Code, AlertTriangle 
} from 'lucide-react';

const AwsConsole = ({ mode = 'admin' }) => {
  const [activeTab, setActiveTab] = useState('ec2'); // 'ec2' | 'security' | 's3' | 'iam'
  const [loading, setLoading] = useState(true);

  // Unified lists
  const [instances, setInstances] = useState([]);
  const [securityGroups, setSecurityGroups] = useState([]);
  const [s3Buckets, setS3Buckets] = useState([]);
  const [iamUsers, setIamUsers] = useState([]);

  // Selection states for details / actions
  const [selectedInstance, setSelectedInstance] = useState(null);
  const [selectedSg, setSelectedSg] = useState(null);
  const [selectedBucket, setSelectedBucket] = useState(null);
  const [selectedUser, setSelectedUser] = useState(null);

  // Form states
  const [newSgName, setNewSgName] = useState('');
  const [newSgDesc, setNewSgDesc] = useState('');
  
  const [newBucketName, setNewBucketName] = useState('');
  
  const [newUserName, setNewUserName] = useState('');
  const [newUserPolicy, setNewUserPolicy] = useState(`{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ec2:StartInstance", "ec2:StopInstance"],
      "Resource": "*"
    }
  ]
}`);

  // Interactive Security Group Rule Form
  const [newRuleType, setNewRuleType] = useState('Inbound');
  const [newRuleProto, setNewRuleProto] = useState('tcp');
  const [newRulePort, setNewRulePort] = useState('80');
  const [newRuleSource, setNewRuleSource] = useState('0.0.0.0/0');

  // Simulated S3 Upload Form
  const [uploadFileName, setUploadFileName] = useState('');
  const [uploadFileSize, setUploadFileSize] = useState('1024');
  const [showRsInfo, setShowRsInfo] = useState(false);
  const [rsDetails, setRsDetails] = useState(null);

  // IAM Policy Tester
  const [testAction, setTestAction] = useState('ec2:StopInstance');
  const [testResource, setTestResource] = useState('*');
  const [testResult, setTestResult] = useState(null);

  // Fetch all AWS status
  const fetchAwsState = async () => {
    try {
      setLoading(true);
      // Fetch state from Go orchestrator
      const res = await fetch('/api/aegis/aws');
      if (!res.ok) throw new Error('Ошибка связи с AWS Orchestrator');
      const data = await res.json();
      
      setSecurityGroups(data.security_groups || []);
      setS3Buckets(data.s3_buckets || []);
      setIamUsers(data.iam_users || []);
      
      // Auto-select first elements if nothing is selected
      if (data.security_groups?.length && !selectedSg) {
        setSelectedSg(data.security_groups[0]);
      }
      if (data.s3_buckets?.length && !selectedBucket) {
        setSelectedBucket(data.s3_buckets[0]);
      }
      if (data.iam_users?.length && !selectedUser) {
        setSelectedUser(data.iam_users[0]);
      }

      // Fetch computational instances (FastAPI VMs + Go Containers)
      const instanceList = [];
      
      // 1. Fetch from FastAPI `/api/vms` (KubeVirt virtual machines)
      try {
        const resVms = await fetch('/api/vms');
        if (resVms.ok) {
          const vmsData = await resVms.json();
          // Filter client-owned VMs in client mode
          const filteredVms = mode === 'client' 
            ? vmsData.filter(vm => vm.name.startsWith('client-') || (vm.labels && vm.labels["hosting.antigravity.io/owner"] === "client-01"))
            : vmsData;

          filteredVms.forEach(vm => {
            instanceList.push({
              id: vm.name,
              name: vm.name,
              type: 'VDS VM (KubeVirt)',
              status: vm.status === 'Running' ? 'Running' : 'Stopped',
              ip: vm.ips && vm.ips[0] ? vm.ips[0] : '10.244.0.12',
              cpu: vm.cpu || 2,
              ram: vm.ram || 4
            });
          });
        }
      } catch (e) {
        console.warn('FastAPI VMs fetch failed, using mock data for local fallback:', e);
      }

      // 2. Fetch from Go orchestrator `/api/aegis/containers` (Aegis Containers)
      try {
        const resContainers = await fetch('/api/aegis/containers');
        if (resContainers.ok) {
          const containersData = await resContainers.json();
          containersData.forEach(c => {
            instanceList.push({
              id: c.id,
              name: c.name,
              type: 'Aegis Container',
              status: c.status === 'Running' ? 'Running' : 'Stopped',
              ip: c.ip || '10.0.99.15',
              cpu: c.cpu_cores || 1,
              ram: c.ram_limit_gb || 2
            });
          });
        } else {
          // Fallback if containers endpoint fails but we have mock values
          if (instanceList.length === 0) {
            instanceList.push(
              { id: 'client-my-db-vds', name: 'client-my-db-vds', type: 'VDS VM (KubeVirt)', status: 'Running', ip: '185.190.140.22', cpu: 2, ram: 4 },
              { id: 'client-web-app', name: 'client-web-app', type: 'VDS VM (KubeVirt)', status: 'Running', ip: '185.190.140.45', cpu: 2, ram: 4 },
              { id: 'client-redis-billing-server', name: 'client-redis-billing-server', type: 'Aegis Container', status: 'Running', ip: '10.0.99.10', cpu: 1, ram: 2 }
            );
          }
        }
      } catch (e) {
        console.warn('Go containers fetch failed:', e);
      }

      setInstances(instanceList);
      if (instanceList.length && !selectedInstance) {
        setSelectedInstance(instanceList[0]);
      }

    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAwsState();
  }, [mode]);

  // Security Groups Actions
  const handleCreateSg = async (e) => {
    e.preventDefault();
    if (!newSgName.trim()) return;

    try {
      const res = await fetch('/api/aegis/aws/security-groups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'create',
          name: newSgName.trim(),
          description: newSgDesc.trim()
        })
      });
      if (!res.ok) throw new Error('Не удалось создать Security Group');
      setNewSgName('');
      setNewSgDesc('');
      await fetchAwsState();
      alert('Группа безопасности создана!');
    } catch (err) {
      alert(err.message);
    }
  };

  const handleAddSgRule = async () => {
    if (!selectedSg) return;

    const newRule = {
      type: newRuleType,
      protocol: newRuleProto,
      port_range: newRulePort,
      source: newRuleSource
    };

    const updatedRules = [...selectedSg.rules, newRule];

    try {
      const res = await fetch('/api/aegis/aws/security-groups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'update_rules',
          id: selectedSg.id,
          rules: updatedRules
        })
      });
      if (!res.ok) throw new Error('Не удалось обновить правила');
      await fetchAwsState();
      // Update local selection
      const updatedSg = securityGroups.find(g => g.id === selectedSg.id);
      if (updatedSg) setSelectedSg(updatedSg);
    } catch (err) {
      alert(err.message);
    }
  };

  const handleDeleteSgRule = async (indexToDelete) => {
    if (!selectedSg) return;

    const updatedRules = selectedSg.rules.filter((_, idx) => idx !== indexToDelete);

    try {
      const res = await fetch('/api/aegis/aws/security-groups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'update_rules',
          id: selectedSg.id,
          rules: updatedRules
        })
      });
      if (!res.ok) throw new Error('Не удалось удалить правило');
      await fetchAwsState();
    } catch (err) {
      alert(err.message);
    }
  };

  const handleBindSg = async (instanceId) => {
    if (!selectedSg) return;

    try {
      const res = await fetch('/api/aegis/aws/security-groups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'bind',
          id: selectedSg.id,
          instance: instanceId
        })
      });
      if (!res.ok) throw new Error('Не удалось привязать SG к инстансу');
      await fetchAwsState();
      alert(`Группа безопасности ${selectedSg.name} привязана к ${instanceId}`);
    } catch (err) {
      alert(err.message);
    }
  };

  // S3 Actions
  const handleCreateBucket = async (e) => {
    e.preventDefault();
    if (!newBucketName.trim()) return;

    // AWS bucket names must be lowercase, no spaces, 3-63 chars
    const cleanName = newBucketName.toLowerCase().replace(/[^a-z0-9.-]/g, '-');

    try {
      const res = await fetch('/api/aegis/aws/s3/buckets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'create',
          name: cleanName
        })
      });
      if (res.status === 409) {
        alert('Бакет с таким именем уже занят глобально в облаке Aegis!');
        return;
      }
      if (!res.ok) throw new Error('Не удалось создать бакет');
      setNewBucketName('');
      await fetchAwsState();
      alert(`S3 Бакет ${cleanName} успешно создан!`);
    } catch (err) {
      alert(err.message);
    }
  };

  const handleToggleBucketPolicy = async (bucketName) => {
    try {
      const res = await fetch('/api/aegis/aws/s3/buckets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'toggle_policy',
          name: bucketName
        })
      });
      if (!res.ok) throw new Error('Не удалось изменить политику доступа');
      await fetchAwsState();
    } catch (err) {
      alert(err.message);
    }
  };

  const handleDeleteBucket = async (bucketName) => {
    if (!confirm(`Вы действительно хотите удалить бакет s3://${bucketName} и все его содержимое?`)) return;
    try {
      const res = await fetch('/api/aegis/aws/s3/buckets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'delete',
          name: bucketName
        })
      });
      if (!res.ok) throw new Error('Не удалось удалить бакет');
      setSelectedBucket(null);
      await fetchAwsState();
    } catch (err) {
      alert(err.message);
    }
  };

  const handleUploadS3Object = async (e) => {
    e.preventDefault();
    if (!selectedBucket || !uploadFileName.trim()) return;

    const size = parseInt(uploadFileSize) * 1024; // KB to Bytes

    try {
      const res = await fetch('/api/aegis/aws/s3/buckets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'upload',
          name: selectedBucket.name,
          key: uploadFileName.trim(),
          size: size
        })
      });
      if (!res.ok) throw new Error('Ошибка загрузки объекта в бакет');
      
      // Compute Reed-Solomon chunk distribution simulation
      const dataNodes = ['S3-Storage-Node-1', 'S3-Storage-Node-2', 'S3-Storage-Node-3', 'S3-Storage-Node-4'];
      const parityNodes = ['S3-Storage-Node-5', 'S3-Storage-Node-6'];
      
      setRsDetails({
        filename: uploadFileName.trim(),
        totalSize: size,
        chunkSize: Math.ceil(size / 4),
        dataNodes,
        parityNodes
      });
      
      setUploadFileName('');
      setShowRsInfo(true);
      await fetchAwsState();
    } catch (err) {
      alert(err.message);
    }
  };

  // IAM Actions
  const handleCreateIAMUser = async (e) => {
    e.preventDefault();
    if (!newUserName.trim()) return;

    try {
      // Validate JSON policy format
      JSON.parse(newUserPolicy);

      const res = await fetch('/api/aegis/aws/iam', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'create',
          username: newUserName.trim(),
          policy: newUserPolicy
        })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || 'Не удалось создать пользователя');
      }
      setNewUserName('');
      await fetchAwsState();
      alert(`IAM Пользователь ${newUserName} успешно создан!`);
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    }
  };

  const handleUpdateIAMUserPolicy = async () => {
    if (!selectedUser) return;

    try {
      JSON.parse(selectedUser.policy); // Syntax check

      const res = await fetch('/api/aegis/aws/iam', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'update_policy',
          username: selectedUser.username,
          policy: selectedUser.policy
        })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || 'Не удалось обновить политику');
      }
      await fetchAwsState();
      alert('Политика безопасности обновлена в реальном времени!');
    } catch (err) {
      alert(`Ошибка синтаксиса: ${err.message}`);
    }
  };

  const handleDeleteIAMUser = async (username) => {
    if (!confirm(`Удалить IAM пользователя ${username}?`)) return;
    try {
      const res = await fetch('/api/aegis/aws/iam', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'delete',
          username: username
        })
      });
      if (!res.ok) throw new Error('Не удалось удалить пользователя');
      setSelectedUser(null);
      await fetchAwsState();
    } catch (err) {
      alert(err.message);
    }
  };

  // Local Evaluator for IAM Policy Simulating AWS behavior
  const handleEvaluatePolicy = () => {
    if (!selectedUser) return;
    
    let policyObj;
    try {
      policyObj = JSON.parse(selectedUser.policy);
    } catch (e) {
      setTestResult({ allowed: false, reason: 'Ошибка разбора JSON политики пользователя' });
      return;
    }

    const statements = policyObj.Statement || [];
    let allowed = false;
    let matchingStmt = null;
    let explicitDeny = false;

    for (let stmt of statements) {
      // Check Resource wildcard or match
      const resourceMatch = stmt.Resource === '*' || stmt.Resource === testResource;
      if (!resourceMatch) continue;

      // Check Action matching
      let actionMatch = false;
      const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
      
      for (let act of actions) {
        if (act === '*' || act === testAction) {
          actionMatch = true;
          break;
        }
        if (act.endsWith(':*')) {
          const prefix = act.split(':')[0];
          const testPrefix = testAction.split(':')[0];
          if (prefix === testPrefix) {
            actionMatch = true;
            break;
          }
        }
      }

      if (actionMatch) {
        if (stmt.Effect === 'Deny') {
          explicitDeny = true;
          matchingStmt = stmt;
          break; // Explicit Deny overrides everything
        }
        if (stmt.Effect === 'Allow') {
          allowed = true;
          matchingStmt = stmt;
        }
      }
    }

    if (explicitDeny) {
      setTestResult({
        allowed: false,
        reason: 'Запрещено: Explicit Deny в политике безопасности!',
        statement: matchingStmt
      });
    } else if (allowed) {
      setTestResult({
        allowed: true,
        reason: 'Разрешено: Совпало с правилом Allow в политике.',
        statement: matchingStmt
      });
    } else {
      setTestResult({
        allowed: false,
        reason: 'Запрещено: По умолчанию (Implicit Deny) — нет совпадающего правила Allow.',
        statement: null
      });
    }
  };

  // Quick policy templates helper
  const handleApplyTemplatePolicy = (templateName) => {
    let policy = '';
    if (templateName === 'admin') {
      policy = `{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ec2:*", "s3:*", "iam:*"],
      "Resource": "*"
    }
  ]
}`;
    } else if (templateName === 'readonly') {
      policy = `{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ec2:DescribeInstances", "s3:ListBucket", "s3:GetObject"],
      "Resource": "*"
    }
  ]
}`;
    } else if (templateName === 'dev') {
      policy = `{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ec2:StartInstance", "ec2:StopInstance"],
      "Resource": "*"
    },
    {
      "Effect": "Deny",
      "Action": ["ec2:TerminateInstance", "s3:DeleteBucket"],
      "Resource": "*"
    }
  ]
}`;
    }

    if (selectedUser) {
      setSelectedUser({ ...selectedUser, policy });
    } else {
      setNewUserPolicy(policy);
    }
  };

  // Check which SG is bound to selectedInstance
  const getBoundSgName = (instanceName) => {
    const bound = securityGroups.find(sg => sg.bound_instances?.includes(instanceName));
    return bound ? bound.name : 'default-vpc-sg';
  };

  const getBoundSgRules = (instanceName) => {
    const bound = securityGroups.find(sg => sg.bound_instances?.includes(instanceName)) || securityGroups[0];
    return bound ? bound.rules : [];
  };

  return (
    <div className="aws-console-dashboard" style={{ color: '#e2e8f0', background: '#0a0e17', border: '1px solid #1e293b', minHeight: '80vh', fontFamily: 'var(--font-sans)' }}>
      
      {/* AWS Top Header bar mimicking real AWS Console */}
      <div className="aws-header-bar" style={{ background: '#19222d', padding: '12px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '2px solid #ff9900' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ background: '#ff9900', color: '#19222d', padding: '6px', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Cloud size={18} />
            <span>AWS</span>
          </div>
          <span style={{ fontSize: '1rem', fontWeight: 600, color: '#f8fafc' }}>
            Aegis Hybrid Infrastructure Console <span style={{ color: '#ff9900', fontSize: '0.8rem' }}>(Consolev2)</span>
          </span>
        </div>

        <div style={{ display: 'flex', gap: '14px', alignItems: 'center' }}>
          <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Регион: <strong style={{ color: '#fff' }}>aegis-east-1 (Ubuntu Node)</strong>
          </span>
          <button 
            onClick={fetchAwsState} 
            className="btn btn-secondary btn-sm" 
            style={{ padding: '6px 8px', background: 'rgba(255,255,255,0.03)' }}
          >
            <RefreshCw size={12} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </div>

      {/* Sub Tabs Navigation */}
      <div className="aws-tab-bar" style={{ display: 'flex', background: '#121824', borderBottom: '1px solid #1e293b' }}>
        {[
          { id: 'ec2', label: 'EC2 Dashboard (Серверы)', icon: <Server size={14} /> },
          { id: 'security', label: 'VPC Security Groups (Сеть)', icon: <Shield size={14} /> },
          { id: 's3', label: 'S3 Console (Хранилище)', icon: <Database size={14} /> },
          { id: 'iam', label: 'IAM (Менеджер прав)', icon: <Key size={14} /> }
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: '14px 20px',
              background: activeTab === tab.id ? '#0a0e17' : 'transparent',
              border: 'none',
              borderBottom: activeTab === tab.id ? '3px solid #ff9900' : '3px solid transparent',
              color: activeTab === tab.id ? '#ff9900' : '#94a3b8',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontSize: '0.85rem'
            }}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Main Content Area */}
      <div style={{ padding: '24px' }}>

        {/* TAB 1: EC2 INSTANCES */}
        {activeTab === 'ec2' && (
          <div className="aws-layout-grid" style={{ display: 'grid', gridTemplateColumns: '1.8fr 1.2fr', gap: '24px' }}>
            
            {/* Instances list */}
            <div>
              <div className="card" style={{ background: '#121824', padding: '20px' }}>
                <h3 style={{ fontSize: '1.2rem', marginTop: 0, marginBottom: '16px', color: '#fff', borderBottom: '1px solid #1e293b', paddingBottom: '10px' }}>
                  Инстансы EC2 (Виртуальные серверы)
                </h3>

                {loading ? (
                  <div style={{ padding: '40px', display: 'flex', justifyContent: 'center' }}><div className="spinner"></div></div>
                ) : instances.length === 0 ? (
                  <p style={{ color: '#94a3b8', textAlign: 'center', padding: '20px' }}>Активные инстансы не обнаружены.</p>
                ) : (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #1e293b', color: '#64748b' }}>
                        <th style={{ padding: '10px 6px' }}>Имя инстанса</th>
                        <th style={{ padding: '10px 6px' }}>Тип</th>
                        <th style={{ padding: '10px 6px' }}>Статус</th>
                        <th style={{ padding: '10px 6px' }}>Внешний IP</th>
                        <th style={{ padding: '10px 6px' }}>Группа безопасности</th>
                      </tr>
                    </thead>
                    <tbody>
                      {instances.map(inst => (
                        <tr 
                          key={inst.id} 
                          onClick={() => setSelectedInstance(inst)}
                          style={{ 
                            borderBottom: '1px solid #1e293b', 
                            cursor: 'pointer',
                            background: selectedInstance?.id === inst.id ? 'rgba(255, 153, 0, 0.04)' : 'transparent',
                            color: selectedInstance?.id === inst.id ? '#ff9900' : '#e2e8f0'
                          }}
                        >
                          <td style={{ padding: '12px 6px', fontWeight: 'bold' }}>{inst.name}</td>
                          <td style={{ padding: '12px 6px', color: '#94a3b8' }}>{inst.type}</td>
                          <td style={{ padding: '12px 6px' }}>
                            <span style={{ 
                              color: inst.status === 'Running' ? '#10b981' : '#ef4444',
                              background: inst.status === 'Running' ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)',
                              padding: '2px 6px',
                              fontSize: '0.75rem',
                              fontWeight: 'bold'
                            }}>
                              {inst.status === 'Running' ? 'running' : 'stopped'}
                            </span>
                          </td>
                          <td style={{ padding: '12px 6px', fontFamily: 'monospace' }}>{inst.ip}</td>
                          <td style={{ padding: '12px 6px', color: '#ff9900' }}>
                            🛡️ {getBoundSgName(inst.name)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              {/* Informative description */}
              <div className="card" style={{ background: '#121824', padding: '16px', marginTop: '20px', fontSize: '0.8rem', color: '#94a3b8' }}>
                <strong style={{ color: '#fff', display: 'block', marginBottom: '6px' }}>AWS Security Group Stateful filtering:</strong>
                Привязка группы безопасности к виртуальной машине автоматически транслируется оркестратором в изолированные правила <code>iptables</code> внутри Linux-неймспейса сервера. Stateful-соединения разрешаются автоматически через сборочный модуль Conntrack.
              </div>
            </div>

            {/* Network Interactive Path Visualizer */}
            <div>
              <div className="card" style={{ background: '#121824', padding: '20px', display: 'flex', flexDirection: 'column', alignItems: 'center', height: '100%' }}>
                <h3 style={{ fontSize: '1.1rem', marginTop: 0, marginBottom: '20px', alignSelf: 'flex-start', color: '#fff' }}>
                  Диаграмма безопасности сети (Network Path)
                </h3>

                {selectedInstance ? (
                  <div style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '24px' }}>
                    
                    {/* Node 1: Internet */}
                    <div style={{ textAlign: 'center', background: '#1e293b', border: '1px solid #475569', padding: '10px 16px', width: '180px', borderRadius: '0px' }}>
                      <span style={{ fontSize: '0.7rem', color: '#94a3b8', display: 'block' }}>ИСТОЧНИК</span>
                      <strong style={{ fontSize: '0.9rem', color: '#fff' }}>Интернет (0.0.0.0/0)</strong>
                    </div>

                    {/* Animated network flow SVG path */}
                    <svg width="60" height="70" viewBox="0 0 60 70">
                      <line x1="30" y1="0" x2="30" y2="70" stroke="#ff9900" strokeWidth="2" strokeDasharray="5,5" className="svg-flow-animation" />
                      <circle cx="30" cy="35" r="4" fill="#ff9900" />
                    </svg>

                    {/* Node 2: Firewall Rules */}
                    <div style={{ 
                      textAlign: 'center', 
                      background: 'rgba(255, 153, 0, 0.05)', 
                      border: '1px solid #ff9900', 
                      padding: '12px 16px', 
                      width: '240px',
                      borderRadius: '0px'
                    }}>
                      <span style={{ fontSize: '0.7rem', color: '#ff9900', display: 'block', fontWeight: 'bold' }}>AWS SECURITY GROUP</span>
                      <strong style={{ fontSize: '0.95rem', color: '#fff' }}>{getBoundSgName(selectedInstance.name)}</strong>
                      
                      <div style={{ marginTop: '10px', textAlign: 'left', fontSize: '0.75rem', background: '#0a0e17', padding: '8px', border: '1px solid #1e293b' }}>
                        <span style={{ color: '#64748b', display: 'block', marginBottom: '4px', fontWeight: 'bold' }}>Разрешенные входящие порты:</span>
                        {getBoundSgRules(selectedInstance.name).map((r, i) => (
                          <div key={i} style={{ color: '#10b981', display: 'flex', justifyContent: 'space-between', fontFamily: 'monospace' }}>
                            <span>👉 TCP {r.port_range}</span>
                            <span style={{ color: '#94a3b8' }}>from {r.source}</span>
                          </div>
                        ))}
                        {getBoundSgRules(selectedInstance.name).length === 0 && (
                          <div style={{ color: '#ef4444' }}>❌ Входящий трафик заблокирован</div>
                        )}
                      </div>
                    </div>

                    {/* Animated network flow SVG path */}
                    <svg width="60" height="70" viewBox="0 0 60 70">
                      <line x1="30" y1="0" x2="30" y2="70" stroke="#10b981" strokeWidth="2" strokeDasharray="5,5" />
                      <polygon points="30,70 25,60 35,60" fill="#10b981" />
                    </svg>

                    {/* Node 3: Target VM */}
                    <div style={{ 
                      textAlign: 'center', 
                      background: 'rgba(16, 185, 129, 0.05)', 
                      border: '1px solid #10b981', 
                      padding: '12px 16px', 
                      width: '220px',
                      borderRadius: '0px'
                    }}>
                      <span style={{ fontSize: '0.7rem', color: '#10b981', display: 'block' }}>ЦЕЛЕВОЙ ИНСТАНС</span>
                      <strong style={{ fontSize: '0.95rem', color: '#fff' }}>{selectedInstance.name}</strong>
                      <span style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', fontFamily: 'monospace', marginTop: '4px' }}>IP: {selectedInstance.ip}</span>
                    </div>

                  </div>
                ) : (
                  <p style={{ color: '#64748b', margin: 'auto' }}>Выберите инстанс слева для анализа сетевого пути.</p>
                )}

              </div>
            </div>

          </div>
        )}

        {/* TAB 2: SECURITY GROUPS */}
        {activeTab === 'security' && (
          <div className="aws-layout-grid" style={{ display: 'grid', gridTemplateColumns: '1.2fr 1.8fr', gap: '24px' }}>
            
            {/* SGs List & Create */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div className="card" style={{ background: '#121824', padding: '20px' }}>
                <h3 style={{ fontSize: '1.1rem', marginTop: 0, marginBottom: '16px', color: '#fff', borderBottom: '1px solid #1e293b', paddingBottom: '10px' }}>
                  Группы безопасности (Security Groups)
                </h3>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {securityGroups.map(sg => (
                    <div 
                      key={sg.id}
                      onClick={() => setSelectedSg(sg)}
                      style={{ 
                        background: selectedSg?.id === sg.id ? 'rgba(255, 153, 0, 0.03)' : 'rgba(0, 0, 0, 0.2)',
                        border: selectedSg?.id === sg.id ? '1px solid #ff9900' : '1px solid #1e293b',
                        padding: '12px 16px',
                        cursor: 'pointer',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center'
                      }}
                    >
                      <div>
                        <strong style={{ color: selectedSg?.id === sg.id ? '#ff9900' : '#fff', fontSize: '0.9rem' }}>{sg.name}</strong>
                        <span style={{ display: 'block', fontSize: '0.72rem', color: '#64748b', marginTop: '2px' }}>{sg.id} | {sg.description}</span>
                      </div>
                      <span style={{ fontSize: '0.75rem', background: '#1a222d', padding: '2px 8px', color: '#ff9900', border: '1px solid rgba(255, 153, 0, 0.15)' }}>
                        {sg.rules?.length || 0} правил
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Create new SG form */}
              <div className="card" style={{ background: '#121824', padding: '20px' }}>
                <h3 style={{ fontSize: '1.1rem', marginTop: 0, marginBottom: '14px', color: '#fff' }}>
                  Создать новую Security Group
                </h3>

                <form onSubmit={handleCreateSg} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', color: '#94a3b8', marginBottom: '4px' }}>Имя группы</label>
                    <input 
                      type="text" 
                      className="form-input" 
                      style={{ width: '100%' }}
                      placeholder="e.g. web-servers-sg" 
                      value={newSgName}
                      onChange={(e) => setNewSgName(e.target.value)}
                      required
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', color: '#94a3b8', marginBottom: '4px' }}>Описание</label>
                    <input 
                      type="text" 
                      className="form-input" 
                      style={{ width: '100%' }}
                      placeholder="e.g. Allow HTTP and SSH" 
                      value={newSgDesc}
                      onChange={(e) => setNewSgDesc(e.target.value)}
                    />
                  </div>
                  <button className="btn btn-primary" type="submit" style={{ padding: '8px', color: '#000', fontWeight: 'bold' }}>
                    <Plus size={14} /> Создать группу
                  </button>
                </form>
              </div>
            </div>

            {/* Selected SG Rules Manager */}
            <div>
              {selectedSg ? (
                <div className="card" style={{ background: '#121824', padding: '20px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #1e293b', paddingBottom: '12px', marginBottom: '16px' }}>
                    <div>
                      <h3 style={{ fontSize: '1.2rem', margin: 0, color: '#fff' }}>
                        Правила группы: <span style={{ color: '#ff9900' }}>{selectedSg.name}</span>
                      </h3>
                      <p style={{ margin: '4px 0 0 0', fontSize: '0.8rem', color: '#94a3b8' }}>ID: {selectedSg.id} — {selectedSg.description}</p>
                    </div>
                  </div>

                  {/* Rules Grid */}
                  <h4 style={{ fontSize: '0.9rem', color: '#ff9900', marginBottom: '10px' }}>Входящие правила (Inbound Rules)</h4>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem', textAlign: 'left', marginBottom: '24px' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #1e293b', color: '#64748b' }}>
                        <th style={{ padding: '8px' }}>Протокол</th>
                        <th style={{ padding: '8px' }}>Порт(ы)</th>
                        <th style={{ padding: '8px' }}>Источник (CIDR)</th>
                        <th style={{ padding: '8px', width: '40px' }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedSg.rules?.map((rule, idx) => (
                        <tr key={idx} style={{ borderBottom: '1px solid #1e293b' }}>
                          <td style={{ padding: '10px 8px', fontWeight: 'bold', color: '#38bdf8' }}>{rule.protocol.toUpperCase()}</td>
                          <td style={{ padding: '10px 8px', fontFamily: 'monospace' }}>{rule.port_range}</td>
                          <td style={{ padding: '10px 8px', fontFamily: 'monospace' }}>{rule.source}</td>
                          <td style={{ padding: '8px' }}>
                            {/* Do not allow deleting outbound default rule if it's there */}
                            {!(rule.type === 'Outbound' && rule.port_range === 'all') && (
                              <button 
                                onClick={() => handleDeleteSgRule(idx)} 
                                style={{ background: 'transparent', border: 'none', color: '#ef4444', cursor: 'pointer' }}
                              >
                                <Trash2 size={12} />
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  {/* Add rule inline form */}
                  <div style={{ background: 'rgba(0,0,0,0.2)', border: '1px solid #1e293b', padding: '16px', marginBottom: '24px' }}>
                    <h5 style={{ margin: '0 0 12px 0', fontSize: '0.85rem', color: '#fff' }}>Добавить входящее правило</h5>
                    <div className="aws-subgrid" style={{ display: 'grid', gridTemplateColumns: '1.2fr 1.2fr 1.5fr 1fr', gap: '10px', alignItems: 'end' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.7rem', color: '#94a3b8', marginBottom: '4px' }}>Протокол</label>
                        <select className="form-input form-select" style={{ width: '100%', padding: '6px' }} value={newRuleProto} onChange={(e) => setNewRuleProto(e.target.value)}>
                          <option value="tcp">TCP</option>
                          <option value="udp">UDP</option>
                          <option value="icmp">ICMP</option>
                        </select>
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.7rem', color: '#94a3b8', marginBottom: '4px' }}>Порт (или all)</label>
                        <input type="text" className="form-input" style={{ width: '100%', padding: '6px' }} value={newRulePort} onChange={(e) => setNewRulePort(e.target.value)} placeholder="80" />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.7rem', color: '#94a3b8', marginBottom: '4px' }}>Источник CIDR</label>
                        <input type="text" className="form-input" style={{ width: '100%', padding: '6px' }} value={newRuleSource} onChange={(e) => setNewRuleSource(e.target.value)} placeholder="0.0.0.0/0" />
                      </div>
                      <button className="btn btn-secondary btn-sm" onClick={handleAddSgRule} style={{ padding: '8px', color: '#fff' }}>
                        Добавить
                      </button>
                    </div>
                  </div>

                  {/* Bind SG to VM */}
                  <div style={{ borderTop: '1px solid #1e293b', paddingTop: '16px' }}>
                    <h5 style={{ margin: '0 0 10px 0', fontSize: '0.85rem', color: '#fff' }}>Привязать эту группу безопасности к инстансу:</h5>
                    <div style={{ display: 'flex', gap: '10px' }}>
                      <select 
                        id="instance-bind-select"
                        className="form-input form-select" 
                        style={{ flex: 1 }}
                      >
                        {instances.map(inst => (
                          <option key={inst.id} value={inst.name}>{inst.name} ({inst.type})</option>
                        ))}
                      </select>
                      <button 
                        className="btn btn-primary btn-sm" 
                        style={{ color: '#000', fontWeight: 'bold' }}
                        onClick={() => {
                          const val = document.getElementById('instance-bind-select').value;
                          if (val) handleBindSg(val);
                        }}
                      >
                        Ассоциировать SG
                      </button>
                    </div>
                  </div>

                </div>
              ) : (
                <div className="card" style={{ background: '#121824', padding: '40px', textAlign: 'center', color: '#64748b' }}>
                  Выберите Security Group слева для управления правилами.
                </div>
              )}
            </div>

          </div>
        )}

        {/* TAB 3: S3 STORAGE */}
        {activeTab === 's3' && (
          <div className="aws-layout-grid" style={{ display: 'grid', gridTemplateColumns: '1.2fr 1.8fr', gap: '24px' }}>
            
            {/* Buckets list & Create */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div className="card" style={{ background: '#121824', padding: '20px' }}>
                <h3 style={{ fontSize: '1.1rem', marginTop: 0, marginBottom: '16px', color: '#fff', borderBottom: '1px solid #1e293b', paddingBottom: '10px' }}>
                  Бакеты S3 (Simple Storage Service)
                </h3>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {s3Buckets.map(bucket => (
                    <div 
                      key={bucket.name}
                      onClick={() => setSelectedBucket(bucket)}
                      style={{ 
                        background: selectedBucket?.name === bucket.name ? 'rgba(255, 153, 0, 0.03)' : 'rgba(0, 0, 0, 0.2)',
                        border: selectedBucket?.name === bucket.name ? '1px solid #ff9900' : '1px solid #1e293b',
                        padding: '12px 16px',
                        cursor: 'pointer',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center'
                      }}
                    >
                      <div>
                        <strong style={{ color: selectedBucket?.name === bucket.name ? '#ff9900' : '#fff', fontSize: '0.9rem' }}>s3://{bucket.name}</strong>
                        <span style={{ display: 'block', fontSize: '0.72rem', color: '#64748b', marginTop: '2px' }}>
                          Регион: {bucket.region} | Доступ: {bucket.access_policy === 'Private' ? '🔒 Private' : '🌐 Public-Read'}
                        </span>
                      </div>
                      <span style={{ fontSize: '0.75rem', background: '#1a222d', padding: '2px 8px', color: '#ff9900', border: '1px solid rgba(255, 153, 0, 0.15)' }}>
                        {bucket.objects?.length || 0} файлов
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Create Bucket Form */}
              <div className="card" style={{ background: '#121824', padding: '20px' }}>
                <h3 style={{ fontSize: '1.1rem', marginTop: 0, marginBottom: '14px', color: '#fff' }}>
                  Создать новый S3 бакет
                </h3>

                <form onSubmit={handleCreateBucket} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', color: '#94a3b8', marginBottom: '4px' }}>Имя бакета (глобально уникальное)</label>
                    <input 
                      type="text" 
                      className="form-input" 
                      style={{ width: '100%' }}
                      placeholder="e.g. my-backups-bucket" 
                      value={newBucketName}
                      onChange={(e) => setNewBucketName(e.target.value)}
                      required
                    />
                  </div>
                  <button className="btn btn-primary" type="submit" style={{ padding: '8px', color: '#000', fontWeight: 'bold' }}>
                    <Plus size={14} /> Создать бакет
                  </button>
                </form>
              </div>
            </div>

            {/* Selected Bucket File Explorer */}
            <div>
              {selectedBucket ? (
                <div className="card" style={{ background: '#121824', padding: '20px' }}>
                  
                  {/* Bucket Header */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #1e293b', paddingBottom: '12px', marginBottom: '16px' }}>
                    <div>
                      <h3 style={{ fontSize: '1.2rem', margin: 0, color: '#fff' }}>
                        Бакет: <span style={{ color: '#ff9900' }}>s3://{selectedBucket.name}</span>
                      </h3>
                      <p style={{ margin: '4px 0 0 0', fontSize: '0.8rem', color: '#94a3b8' }}>
                        Права: {selectedBucket.access_policy === 'Private' ? '🔒 Приватный (Private)' : '🌐 Публичный (Public-Read)'}
                      </p>
                    </div>

                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button 
                        onClick={() => handleToggleBucketPolicy(selectedBucket.name)}
                        className={`btn btn-sm ${selectedBucket.access_policy === 'Private' ? 'btn-secondary' : 'btn-primary'}`}
                        style={{ color: selectedBucket.access_policy === 'Private' ? '#fff' : '#000' }}
                      >
                        {selectedBucket.access_policy === 'Private' ? <Unlock size={12} /> : <Lock size={12} />} 
                        {selectedBucket.access_policy === 'Private' ? 'Сделать Публичным' : 'Сделать Приватным'}
                      </button>
                      <button 
                        onClick={() => handleDeleteBucket(selectedBucket.name)}
                        className="btn btn-danger btn-sm"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </div>

                  {/* Objects list */}
                  <h4 style={{ fontSize: '0.9rem', color: '#ff9900', marginBottom: '10px' }}>Объекты / Файлы</h4>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem', textAlign: 'left', marginBottom: '24px' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #1e293b', color: '#64748b' }}>
                        <th style={{ padding: '8px' }}>Имя объекта (Key)</th>
                        <th style={{ padding: '8px' }}>Размер</th>
                        <th style={{ padding: '8px' }}>Последнее обновление</th>
                        <th style={{ padding: '8px', textAlign: 'right' }}>Слой избыточности</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedBucket.objects?.map((obj, idx) => (
                        <tr key={idx} style={{ borderBottom: '1px solid #1e293b' }}>
                          <td style={{ padding: '10px 8px', fontWeight: 'bold', color: '#fff', fontFamily: 'monospace' }}>{obj.key}</td>
                          <td style={{ padding: '10px 8px' }}>{(obj.size / 1024).toFixed(2)} KB</td>
                          <td style={{ padding: '10px 8px', color: '#94a3b8' }}>{obj.last_update}</td>
                          <td style={{ padding: '10px 8px', textAlign: 'right', color: '#10b981', fontWeight: 'bold' }}>
                            Reed-Solomon (4+2)
                          </td>
                        </tr>
                      ))}
                      {(!selectedBucket.objects || selectedBucket.objects.length === 0) && (
                        <tr>
                          <td colSpan="4" style={{ padding: '20px', textAlign: 'center', color: '#64748b' }}>Бакет пуст. Загрузите файлы ниже.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>

                  {/* Simulate Object Upload Form */}
                  <div style={{ background: 'rgba(0,0,0,0.2)', border: '1px solid #1e293b', padding: '16px' }}>
                    <h5 style={{ margin: '0 0 12px 0', fontSize: '0.85rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <Code size={14} color="#ff9900" />
                      Загрузить объект (Имитация S3 API PUT)
                    </h5>
                    
                    <form onSubmit={handleUploadS3Object} className="aws-subgrid" style={{ display: 'grid', gridTemplateColumns: '2fr 1.2fr 1fr', gap: '12px', alignItems: 'end' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.7rem', color: '#94a3b8', marginBottom: '4px' }}>Ключ / Путь к файлу</label>
                        <input 
                          type="text" 
                          className="form-input" 
                          style={{ width: '100%', padding: '6px' }} 
                          value={uploadFileName}
                          onChange={(e) => setUploadFileName(e.target.value)}
                          placeholder="logs/app-vds-back.tar.gz" 
                          required
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.7rem', color: '#94a3b8', marginBottom: '4px' }}>Имит. размер (KB)</label>
                        <input 
                          type="number" 
                          className="form-input" 
                          style={{ width: '100%', padding: '6px' }} 
                          value={uploadFileSize}
                          onChange={(e) => setUploadFileSize(e.target.value)}
                          placeholder="1024"
                          min="1" 
                          required
                        />
                      </div>
                      <button className="btn btn-primary btn-sm" type="submit" style={{ padding: '8px', color: '#000', fontWeight: 'bold' }}>
                        Закачать
                      </button>
                    </form>
                  </div>

                </div>
              ) : (
                <div className="card" style={{ background: '#121824', padding: '40px', textAlign: 'center', color: '#64748b' }}>
                  Выберите бакет слева для просмотра хранящихся объектов.
                </div>
              )}
            </div>

          </div>
        )}

        {/* TAB 4: IAM MANAGER */}
        {activeTab === 'iam' && (
          <div className="aws-layout-grid" style={{ display: 'grid', gridTemplateColumns: '1.2fr 1.8fr', gap: '24px' }}>
            
            {/* Users list & Create */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div className="card" style={{ background: '#121824', padding: '20px' }}>
                <h3 style={{ fontSize: '1.1rem', marginTop: 0, marginBottom: '16px', color: '#fff', borderBottom: '1px solid #1e293b', paddingBottom: '10px' }}>
                  Пользователи IAM (Identity & Access Management)
                </h3>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {iamUsers.map(user => (
                    <div 
                      key={user.username}
                      onClick={() => {
                        setSelectedUser(user);
                        setTestResult(null);
                      }}
                      style={{ 
                        background: selectedUser?.username === user.username ? 'rgba(255, 153, 0, 0.03)' : 'rgba(0, 0, 0, 0.2)',
                        border: selectedUser?.username === user.username ? '1px solid #ff9900' : '1px solid #1e293b',
                        padding: '12px 16px',
                        cursor: 'pointer',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center'
                      }}
                    >
                      <div>
                        <strong style={{ color: selectedUser?.username === user.username ? '#ff9900' : '#fff', fontSize: '0.9rem' }}>👤 {user.username}</strong>
                        <span style={{ display: 'block', fontSize: '0.72rem', color: '#64748b', marginTop: '2px' }}>
                          Создан: {user.joined_at}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Create User Form */}
              <div className="card" style={{ background: '#121824', padding: '20px' }}>
                <h3 style={{ fontSize: '1.1rem', marginTop: 0, marginBottom: '14px', color: '#fff' }}>
                  Создать IAM Пользователя
                </h3>

                <form onSubmit={handleCreateIAMUser} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', color: '#94a3b8', marginBottom: '4px' }}>Имя пользователя</label>
                    <input 
                      type="text" 
                      className="form-input" 
                      style={{ width: '100%' }}
                      placeholder="e.g. dev-developer-01" 
                      value={newUserName}
                      onChange={(e) => setNewUserName(e.target.value)}
                      required
                    />
                  </div>
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      <label style={{ fontSize: '0.75rem', color: '#94a3b8' }}>JSON Политика доступа</label>
                      <div style={{ display: 'flex', gap: '4px' }}>
                        <button type="button" onClick={() => handleApplyTemplatePolicy('admin')} style={{ padding: '2px 4px', fontSize: '0.65rem', background: '#1e293b', border: '1px solid #334155', color: '#fff', cursor: 'pointer' }}>FullAdmin</button>
                        <button type="button" onClick={() => handleApplyTemplatePolicy('dev')} style={{ padding: '2px 4px', fontSize: '0.65rem', background: '#1e293b', border: '1px solid #334155', color: '#fff', cursor: 'pointer' }}>Developer</button>
                        <button type="button" onClick={() => handleApplyTemplatePolicy('readonly')} style={{ padding: '2px 4px', fontSize: '0.65rem', background: '#1e293b', border: '1px solid #334155', color: '#fff', cursor: 'pointer' }}>ReadOnly</button>
                      </div>
                    </div>
                    <textarea 
                      className="form-input" 
                      style={{ width: '100%', height: '140px', fontFamily: 'monospace', fontSize: '0.8rem', background: '#0a0e17' }}
                      value={newUserPolicy}
                      onChange={(e) => setNewUserPolicy(e.target.value)}
                      required
                    />
                  </div>
                  <button className="btn btn-primary" type="submit" style={{ padding: '8px', color: '#000', fontWeight: 'bold' }}>
                    <Plus size={14} /> Создать и привязать
                  </button>
                </form>
              </div>
            </div>

            {/* Selected User Policy Document & Tester */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {selectedUser ? (
                <>
                  <div className="card" style={{ background: '#121824', padding: '20px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #1e293b', paddingBottom: '12px', marginBottom: '16px' }}>
                      <div>
                        <h3 style={{ fontSize: '1.2rem', margin: 0, color: '#fff' }}>
                          JSON Документ прав: <span style={{ color: '#ff9900' }}>{selectedUser.username}</span>
                        </h3>
                        <p style={{ margin: '4px 0 0 0', fontSize: '0.8rem', color: '#94a3b8' }}>Привязанные права в формате AWS IAM JSON</p>
                      </div>

                      <div>
                        <button 
                          onClick={() => handleDeleteIAMUser(selectedUser.username)}
                          className="btn btn-danger btn-sm"
                        >
                          Удалить пользователя
                        </button>
                      </div>
                    </div>

                    <div style={{ position: 'relative' }}>
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '4px', marginBottom: '6px', position: 'absolute', right: '10px', top: '10px', zIndex: 10 }}>
                        <button type="button" onClick={() => handleApplyTemplatePolicy('admin')} style={{ padding: '2px 4px', fontSize: '0.65rem', background: '#1e293b', border: '1px solid #334155', color: '#fff', cursor: 'pointer' }}>FullAdmin</button>
                        <button type="button" onClick={() => handleApplyTemplatePolicy('dev')} style={{ padding: '2px 4px', fontSize: '0.65rem', background: '#1e293b', border: '1px solid #334155', color: '#fff', cursor: 'pointer' }}>Developer</button>
                        <button type="button" onClick={() => handleApplyTemplatePolicy('readonly')} style={{ padding: '2px 4px', fontSize: '0.65rem', background: '#1e293b', border: '1px solid #334155', color: '#fff', cursor: 'pointer' }}>ReadOnly</button>
                      </div>
                      
                      <textarea
                        className="form-input"
                        style={{ 
                          width: '100%', 
                          height: '240px', 
                          fontFamily: 'monospace', 
                          fontSize: '0.82rem', 
                          background: '#070a13', 
                          color: '#56c8f9',
                          padding: '14px',
                          border: '1px solid #1e293b'
                        }}
                        value={selectedUser.policy}
                        onChange={(e) => setSelectedUser({ ...selectedUser, policy: e.target.value })}
                      />
                    </div>

                    <button 
                      onClick={handleUpdateIAMUserPolicy}
                      className="btn btn-primary btn-sm" 
                      style={{ color: '#000', fontWeight: 'bold', marginTop: '12px' }}
                    >
                      Сохранить и применить политику
                    </button>
                  </div>

                  {/* Policy Simulator Tool */}
                  <div className="card" style={{ background: '#121824', padding: '20px' }}>
                    <h3 style={{ fontSize: '1.1rem', marginTop: 0, marginBottom: '14px', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <Shield size={16} color="#ff9900" />
                      Симулятор политик доступа (IAM Policy Simulator)
                    </h3>

                    <div className="aws-subgrid" style={{ display: 'grid', gridTemplateColumns: '2fr 2fr 1fr', gap: '12px', alignItems: 'end', marginBottom: '16px' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.75rem', color: '#94a3b8', marginBottom: '4px' }}>Запрашиваемое действие (Action)</label>
                        <select 
                          className="form-input" 
                          style={{ width: '100%', padding: '6px' }}
                          value={testAction}
                          onChange={(e) => setTestAction(e.target.value)}
                        >
                          <option value="ec2:StartInstance">ec2:StartInstance (Запуск ВМ)</option>
                          <option value="ec2:StopInstance">ec2:StopInstance (Остановка ВМ)</option>
                          <option value="ec2:TerminateInstance">ec2:TerminateInstance (Удаление ВМ)</option>
                          <option value="s3:ListBucket">s3:ListBucket (Просмотр S3 бакета)</option>
                          <option value="s3:PutObject">s3:PutObject (Запись в S3 бакет)</option>
                          <option value="s3:DeleteBucket">s3:DeleteBucket (Удаление S3 бакета)</option>
                        </select>
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.75rem', color: '#94a3b8', marginBottom: '4px' }}>Ресурс (ARN Resource)</label>
                        <input 
                          type="text" 
                          className="form-input" 
                          style={{ width: '100%', padding: '6px' }}
                          value={testResource}
                          onChange={(e) => setTestResource(e.target.value)}
                          placeholder="*"
                        />
                      </div>
                      <button 
                        className="btn btn-secondary btn-sm" 
                        style={{ padding: '8px', color: '#ff9900', fontWeight: 'bold' }}
                        onClick={handleEvaluatePolicy}
                      >
                        Запустить тест
                      </button>
                    </div>

                    {testResult && (
                      <div style={{ 
                        background: testResult.allowed ? 'rgba(16,185,129,0.06)' : 'rgba(239,68,68,0.06)',
                        border: testResult.allowed ? '1px solid #10b981' : '1px solid #ef4444',
                        padding: '16px',
                        display: 'flex',
                        gap: '12px',
                        alignItems: 'flex-start'
                      }}>
                        <div style={{ 
                          background: testResult.allowed ? '#10b981' : '#ef4444', 
                          color: '#000', 
                          borderRadius: '50%', 
                          width: '24px', 
                          height: '24px', 
                          display: 'flex', 
                          alignItems: 'center', 
                          justifyContent: 'center',
                          flexShrink: 0
                        }}>
                          {testResult.allowed ? <Check size={14} /> : <X size={14} />}
                        </div>
                        <div>
                          <strong style={{ display: 'block', fontSize: '0.9rem', color: testResult.allowed ? '#10b981' : '#ef4444' }}>
                            {testResult.allowed ? 'ALLOWED (Разрешено)' : 'DENIED (Заблокировано)'}
                          </strong>
                          <span style={{ fontSize: '0.8rem', color: '#94a3b8', display: 'block', marginTop: '4px' }}>
                            {testResult.reason}
                          </span>
                          {testResult.statement && (
                            <pre style={{ margin: '8px 0 0 0', padding: '6px', background: '#070a13', border: '1px solid #1e293b', fontSize: '0.75rem', fontFamily: 'monospace', color: '#e2e8f0' }}>
                              {JSON.stringify(testResult.statement, null, 2)}
                            </pre>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <div className="card" style={{ background: '#121824', padding: '40px', textAlign: 'center', color: '#64748b' }}>
                  Выберите IAM пользователя слева для моделирования и управления доступом.
                </div>
              )}
            </div>

          </div>
        )}

      </div>

      {/* Reed-Solomon Erasure Coding Info Modal */}
      {showRsInfo && rsDetails && (
        <div className="console-modal-backdrop">
          <div className="card" style={{ width: '560px', background: '#121824', border: '1px solid #ff9900', padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid #1e293b', paddingBottom: '10px', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '1.2rem', margin: 0, color: '#ff9900', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Database size={20} />
                Детали дистрибуции Reed-Solomon S3
              </h3>
              <button className="btn btn-secondary btn-sm" onClick={() => setShowRsInfo(false)}>
                <X size={14} />
              </button>
            </div>

            <div style={{ fontSize: '0.85rem', color: '#94a3b8', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <p>
                Загруженный файл <strong style={{ color: '#fff', fontFamily: 'monospace' }}>{rsDetails.filename}</strong> ({(rsDetails.totalSize / 1024).toFixed(2)} KB) обработан алгоритмом кодирования стирания **Reed-Solomon (4+2)**:
              </p>

              {/* Shard breakdown visual cards */}
              <div className="aws-rs-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '6px', textAlign: 'center' }}>
                {[...Array(6)].map((_, i) => {
                  const isParity = i >= 4;
                  return (
                    <div 
                      key={i} 
                      style={{ 
                        background: isParity ? 'rgba(255, 153, 0, 0.05)' : 'rgba(16, 185, 129, 0.05)',
                        border: isParity ? '1px stroke #ff9900' : '1px stroke #10b981',
                        padding: '8px 2px',
                        fontSize: '0.7rem'
                      }}
                    >
                      <strong style={{ display: 'block', color: isParity ? '#ff9900' : '#10b981' }}>
                        {isParity ? `P${i-3}` : `D${i+1}`}
                      </strong>
                      <span style={{ fontSize: '0.6rem', color: '#64748b' }}>
                        {isParity ? 'Parity' : 'Data'}
                      </span>
                    </div>
                  );
                })}
              </div>

              {/* Distribution map */}
              <div style={{ background: '#0a0e17', border: '1px solid #1e293b', padding: '12px' }}>
                <strong style={{ fontSize: '0.78rem', color: '#fff', display: 'block', marginBottom: '8px' }}>
                  Размещение чанков на физических узлах хранения:
                </strong>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.75rem', fontFamily: 'monospace' }}>
                  {rsDetails.dataNodes.map((node, idx) => (
                    <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', color: '#e2e8f0' }}>
                      <span>📁 Блок Данных D{idx+1} ({rsDetails.chunkSize} Bytes)</span>
                      <span style={{ color: '#10b981' }}>➔ записан на {node} (Online)</span>
                    </div>
                  ))}
                  {rsDetails.parityNodes.map((node, idx) => (
                    <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', color: '#e2e8f0' }}>
                      <span>⚙️ Блок Паритета P{idx+1} ({rsDetails.chunkSize} Bytes)</span>
                      <span style={{ color: '#ff9900' }}>➔ записан на {node} (Online)</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Warning/Guarantee note */}
              <div style={{ background: 'rgba(16,185,129,0.06)', border: '1px solid #10b981', padding: '10px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                <AlertTriangle size={16} color="#10b981" />
                <span style={{ fontSize: '0.78rem', color: '#10b981' }}>
                  <strong>Гарантия Aegis-HCI:</strong> Данные будут полностью сохранны и доступны для чтения, даже если любые 2 ноды хранения одновременно выйдут из строя.
                </span>
              </div>
            </div>
            
            <button className="btn btn-primary" onClick={() => setShowRsInfo(false)} style={{ width: '100%', padding: '10px', marginTop: '16px', color: '#000', fontWeight: 'bold' }}>
              Отлично
            </button>
          </div>
        </div>
      )}

      {/* Embedded CSS styles */}
      <style>{`
        .svg-flow-animation {
          stroke-dasharray: 8;
          animation: svgFlow 1s linear infinite;
        }
        @keyframes svgFlow {
          to {
            stroke-dashoffset: -16;
          }
        }
        .spin {
          animation: spinAnimation 1s linear infinite;
        }
        @keyframes spinAnimation {
          to { transform: rotate(360deg); }
        }
        .aws-console-dashboard tr:hover {
          background: rgba(255, 255, 255, 0.01);
        }
        @media (max-width: 1024px) {
          .aws-layout-grid {
            grid-template-columns: 1fr !important;
          }
          .aws-subgrid {
            grid-template-columns: 1fr !important;
          }
          .aws-header-bar {
            flex-direction: column !important;
            gap: 12px !important;
            align-items: flex-start !important;
          }
          .aws-tab-bar {
            flex-wrap: wrap !important;
          }
          .aws-tab-bar button {
            flex: 1 1 auto !important;
            padding: 10px 12px !important;
            text-align: center !important;
            justify-content: center !important;
          }
          .aws-rs-grid {
            grid-template-columns: repeat(3, 1fr) !important;
          }
        }
      `}</style>
      
    </div>
  );
};

export default AwsConsole;
