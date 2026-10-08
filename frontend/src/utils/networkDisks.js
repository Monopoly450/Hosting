export function networkDiskState(volume) {
    const reserved = volume.status === 'Reserved';
    const attached = volume.status === 'Attached' || Boolean(volume.attached_vm_name);
    const note = volume.attachment_type === 'creation'
        ? 'Подключён при создании ВМ'
        : volume.attachment_type === 'multiple'
            ? 'Диск используется несколькими ВМ'
            : reserved ? 'Ожидается подключение к ВМ' : '';
    return {
        label: reserved ? 'Подключается' : attached ? 'Подключён' : 'Свободен',
        active: attached && !reserved,
        busy: attached || reserved,
        canDetach: attached && !reserved && volume.can_detach !== false,
        canDelete: !reserved && volume.can_delete !== false,
        note,
    };
}
