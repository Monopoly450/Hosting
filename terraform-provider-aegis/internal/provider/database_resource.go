package provider

import (
	"context"
	"errors"
	"fmt"
	"strconv"

	"github.com/byteburners/terraform-provider-aegis/internal/client"

	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringdefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

var (
	_ resource.Resource                = (*databaseResource)(nil)
	_ resource.ResourceWithConfigure   = (*databaseResource)(nil)
	_ resource.ResourceWithImportState = (*databaseResource)(nil)
)

type databaseResource struct {
	client *client.Client
}

func NewDatabaseResource() resource.Resource {
	return &databaseResource{}
}

type databaseResourceModel struct {
	ID         types.String `tfsdk:"id"`
	Name       types.String `tfsdk:"name"`
	Engine     types.String `tfsdk:"engine"`
	DBUser     types.String `tfsdk:"db_user"`
	DBPassword types.String `tfsdk:"db_password"`
	DBHost     types.String `tfsdk:"db_host"`
	Status     types.String `tfsdk:"status"`
}

func (r *databaseResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_database"
}

func (r *databaseResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	replace := []planmodifier.String{stringplanmodifier.RequiresReplace()}
	resp.Schema = schema.Schema{
		MarkdownDescription: "Управляемая база данных (PostgreSQL или MySQL) в панели ByteBurners.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				MarkdownDescription: "Числовой идентификатор базы данных.",
				Computed:            true,
				PlanModifiers:       []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
			},
			"name": schema.StringAttribute{
				MarkdownDescription: "Имя базы данных (a-z, 0-9, `_`).",
				Required:            true,
				PlanModifiers:       replace,
			},
			"engine": schema.StringAttribute{
				MarkdownDescription: "СУБД: `postgresql` (по умолчанию) или `mysql`.",
				Optional:            true,
				Computed:            true,
				Default:             stringdefault.StaticString("postgresql"),
				PlanModifiers:       replace,
			},
			"db_user": schema.StringAttribute{
				MarkdownDescription: "Сгенерированное имя пользователя БД.",
				Computed:            true,
			},
			"db_password": schema.StringAttribute{
				MarkdownDescription: "Сгенерированный пароль пользователя БД.",
				Computed:            true,
				Sensitive:           true,
			},
			"db_host": schema.StringAttribute{
				MarkdownDescription: "Внутренний хост для подключения к БД.",
				Computed:            true,
			},
			"status": schema.StringAttribute{
				MarkdownDescription: "Текущий статус базы данных.",
				Computed:            true,
			},
		},
	}
}

func (r *databaseResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
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

func (r *databaseResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan databaseResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	db, err := r.client.CreateDatabase(ctx, client.DBCreate{
		Name:   plan.Name.ValueString(),
		Engine: plan.Engine.ValueString(),
	})
	if err != nil {
		resp.Diagnostics.AddError("Не удалось создать базу данных", err.Error())
		return
	}

	applyDBFields(&plan, db)
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *databaseResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state databaseResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, err := strconv.ParseInt(state.ID.ValueString(), 10, 64)
	if err != nil {
		resp.Diagnostics.AddError("Некорректный идентификатор БД", err.Error())
		return
	}

	db, err := r.client.GetDatabase(ctx, id)
	if errors.Is(err, client.ErrNotFound) {
		resp.State.RemoveResource(ctx)
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Не удалось прочитать состояние БД", err.Error())
		return
	}

	applyDBFields(&state, db)
	resp.Diagnostics.Append(resp.State.Set(ctx, &state)...)
}

// Update не выполняет реальных изменений: все настраиваемые поля RequiresReplace.
func (r *databaseResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan databaseResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *databaseResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state databaseResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	id, err := strconv.ParseInt(state.ID.ValueString(), 10, 64)
	if err != nil {
		resp.Diagnostics.AddError("Некорректный идентификатор БД", err.Error())
		return
	}
	if err := r.client.DeleteDatabase(ctx, id); err != nil {
		resp.Diagnostics.AddError("Не удалось удалить базу данных", err.Error())
	}
}

func (r *databaseResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	// Импорт по числовому id: terraform import aegis_database.example 5
	resp.Diagnostics.Append(resp.State.SetAttribute(ctx, pathID, req.ID)...)
}

func applyDBFields(m *databaseResourceModel, db *client.Database) {
	m.ID = types.StringValue(strconv.FormatInt(db.ID, 10))
	m.Name = types.StringValue(db.DBName)
	m.Engine = types.StringValue(db.Engine)
	m.DBUser = types.StringValue(db.DBUser)
	m.DBPassword = types.StringValue(db.DBPassword)
	m.DBHost = types.StringValue(db.DBHost)
	m.Status = types.StringValue(db.Status)
}
