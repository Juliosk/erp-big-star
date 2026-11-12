// Sessão: permissões, empresas e empresa de trabalho.
import { api, setToken, clearToken } from "./api.js";

export const session = {
  connected: false,
  devAuth: false,
  permissions: new Set(),
  companies: [],
  company: "",
  can(permission) { return this.permissions.has(permission); },
  get q() { return `company_id=${encodeURIComponent(this.company)}`; },
  get companyName() {
    const c = this.companies.find((x) => x.id === this.company);
    return c ? c.trade_name || c.legal_name : "—";
  },
  async connect(token) {
    setToken(token);
    try {
      const context = await api("admin/session-context");
      const { items } = await api("admin/companies?status=ACTIVE");
      this.permissions = new Set(context.permissions);
      this.devAuth = Boolean(context.development_auth);
      this.companies = items;
      this.company = items[0]?.id || "";
      this.connected = true;
    } catch (error) {
      clearToken();
      throw error;
    }
  },
  disconnect() {
    clearToken();
    this.connected = false;
    this.permissions = new Set();
    this.companies = [];
    this.company = "";
  },
};
