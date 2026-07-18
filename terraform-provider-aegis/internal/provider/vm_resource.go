package provider

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/byteburners/terraform-provider-aegis/internal/client"

	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/booldefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

var (
	_ resource.Resource                = (*vmResource)(nil)
	_ resource.ResourceWithConfigure   = (*vmResource)(nil)
	_ resource.ResourceWithImportState = (*vmResource)(nil)
)

type vmResource struct {
	client *client.Client
}

func NewVMResource() resource.Resource {
	return &vmResource{}
}

type vmResourceModel struct {
	ID          types.String `tfsdk:"id"`
	Name        types.String `tfsdk:"name"`
	OSType      types.String `tfsdk:"os_type"`
	CPUCores    types.Int64  `tfsdk:"cpu_cores"`
	MemoryGB    types.Int64  `tfsdk:"memory_gb"`
	DiskGB      types.Int64  `tfsdk:"disk_gb"`
	CustomImage types.String `tfsdk:"custom_image"`
	WaitForIP   types.Bool   `tfsdk:"wait_for_ip"`
	TaskID      types.Int64  `tfsdk:"task_id"`
	Status      types.String `tfsdk:"status"`
	IPAddress   types.String `tfsdk:"ip_address"`
	SSHPort     types.Int64  `tfsdk:"ssh_port"`
}

func (r *vmResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_vm"
}

func (r *vmResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	replace := []planmodifier.String{stringplanmodifier.RequiresReplace()}
	resp.Schema = schema.Schema{
		MarkdownDescription: "Виртуальная машина в панели ByteBurners. Изменение любого из параметров " +
			"создания (имя, ОС, CPU, память, диск) пересоздаёт машину.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				MarkdownDescription: "Идентификатор ресурса (совпадает с именем ВМ).",
				Computed:            true,
				PlanModifiers:       []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
			},
			"name": schema.StringAttribute{
				MarkdownDescription: "Имя ВМ (a-z, 0-9, дефис).",
				Required:            true,
				PlanModifiers:       replace,
			},
			"os_type": schema.StringAttribute{
				MarkdownDescription: "Тип ОС: `ubuntu`, `debian`, `windows`, `proxmox`, `truenas`, `custom` и т.д.",
				Required:            true,
				PlanModifiers:       replace,
			},
			"cpu_cores": schema.Int64Attribute{
				MarkdownDescription: "Количество ядер CPU (1–16).",
				Required:            true,
				PlanModifiers:       requiresReplaceInt(),
			},
			"memory_gb": schema.Int64Attribute{
				MarkdownDescription: "Объём ОЗУ в ГБ (1–64).",
				Required:            true,
				PlanModifiers:       requiresReplaceInt(),
			},
			"disk_gb": schema.Int64Attribute{
				MarkdownDescription: "Размер системного диска в ГБ (10–500).",
				Required:            true,
				PlanModifiers:       requiresReplaceInt(),
			},
			"custom_image": schema.StringAttribute{
				MarkdownDescription: "Имя файла кастомного образа (если `os_type = custom`).",
				Optional:            true,
				PlanModifiers:       replace,
			},
			"wait_for_ip": schema.BoolAttribute{
				MarkdownDescription: "Ждать выдачи IP-адреса при создании (по умолчанию `true`). " +
					"Отключите для ISO-образов (Windows/Proxmox/TrueNAS), которым нужна ручная установка.",
				Optional: true,
				Computed: true,
				Default:  booldefault.StaticBool(true),
			},
			"task_id": schema.Int64Attribute{
				MarkdownDescription: "Числовой ID задачи создания ВМ в панели.",
				Computed:            true,
			},
			"status": schema.StringAttribute{
				MarkdownDescription: "Текущий статус ВМ (Pending, Running, Stopped и т.д.).",
				Computed:            true,
			},
			"ip_address": schema.StringAttribute{
				MarkdownDescription: "Основной IP-адрес ВМ.",
				Computed:            true,
			},
			"ssh_port": schema.Int64Attribute{
				MarkdownDescription: "Внешний порт для SSH-подключения.",
				Computed:            true,
			},
		},
	}
}

func (r *vmResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	if req.ProviderData == nil {
		return
	}
	c, ok := req.ProviderData.(*client.Client)
	if !ok {
		resp.Diagnostics.AddError("Некорректный тип клиента",
			fmt.Sprintf("Ожидался *client.Client, получен %T", req.ProviderData))
		return
	}
	r.client = c
}

func (r *vmResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan vmResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	created, err := r.client.CreateVM(ctx, client.VMCreate{
		Name:        plan.Name.ValueString(),
		OSType:      plan.OSType.ValueString(),
		CPUCores:    plan.CPUCores.ValueInt64(),
		MemoryGB:    plan.MemoryGB.ValueInt64(),
		DiskGB:      plan.DiskGB.ValueInt64(),
		CustomImage: plan.CustomImage.ValueString(),
	})
	if err != nil {
		resp.Diagnostics.AddError("Не удалось создать ВМ", err.Error())
		return
	}

	plan.ID = types.StringValue(plan.Name.ValueString())
	plan.TaskID = types.Int64Value(created.TaskID)

	// Дожидаемся появления ВМ и (опционально) IP-адреса.
	vm := r.waitForVM(ctx, plan.Name.ValueString(), plan.WaitForIP.ValueBool())
	applyVMComputed(&plan, vm)

	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *vmResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state vmResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	vm, err := r.client.GetVM(ctx, state.Name.ValueString())
	if errors.Is(err, client.ErrNotFound) {
		resp.State.RemoveResource(ctx)
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Не удалось прочитать состояние ВМ", err.Error())
		return
	}

	applyVMComputed(&state, vm)
	resp.Diagnostics.Append(resp.State.Set(ctx, &state)...)
}

// Update вызывается только для не-RequiresReplace атрибутов (wait_for_ip):
// просто сохраняем план как новое состояние.
func (r *vmResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan vmResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	if vm, err := r.client.GetVM(ctx, plan.Name.ValueString()); err == nil {
		applyVMComputed(&plan, vm)
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *vmResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state vmResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	if err := r.client.DeleteVM(ctx, state.Name.ValueString()); err != nil {
		resp.Diagnostics.AddError("Не удалось удалить ВМ", err.Error())
	}
}

func (r *vmResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	// Импорт по имени ВМ: terraform import aegis_vm.example my-vm-name
	resp.Diagnostics.Append(resp.State.SetAttribute(ctx, pathID, req.ID)...)
	resp.Diagnostics.Append(resp.State.SetAttribute(ctx, pathName, req.ID)...)
}

// waitForVM опрашивает панель, пока ВМ не появится и (если waitIP) не получит IP.
// Возвращает последнее полученное состояние ВМ (может быть nil, если так и не появилась).
func (r *vmResource) waitForVM(ctx context.Context, name string, waitIP bool) *client.VM {
	deadline := time.Now().Add(8 * time.Minute)
	var last *client.VM
	for {
		vm, err := r.client.GetVM(ctx, name)
		if err == nil {
			last = vm
			if !waitIP || vm.PrimaryIP() != "" {
				return last
			}
		}
		if time.Now().After(deadline) || ctx.Err() != nil {
			return last
		}
		select {
		case <-ctx.Done():
			return last
		case <-time.After(10 * time.Second):
		}
	}
}

// applyVMComputed переносит вычисляемые поля из ответа API в модель ресурса.
func applyVMComputed(m *vmResourceModel, vm *client.VM) {
	if vm == nil {
		m.Status = types.StringValue("Pending")
		m.IPAddress = types.StringValue("")
		m.SSHPort = types.Int64Null()
		return
	}
	m.Status = types.StringValue(vm.Status)
	m.IPAddress = types.StringValue(vm.PrimaryIP())
	if vm.SSHPort != nil {
		m.SSHPort = types.Int64Value(*vm.SSHPort)
	} else {
		m.SSHPort = types.Int64Null()
	}
}
