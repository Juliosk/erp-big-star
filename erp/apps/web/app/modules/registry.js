// Catálogo de telas do menu. "soon" = ainda não migrada para o front novo.
import { pedidoVenda } from "./pedido-venda.js";

const soon = (id, title, group, code) => ({ id, title, group, code, soon: true });

export const MODULES = [
  pedidoVenda,
  soon("liberacao-estoque", "Liberação de Estoque", "Faturamento", "M5"),
  soon("liberacao-credito", "Liberação de Crédito", "Faturamento", "—"),
  soon("nota-saida", "Nota Fiscal de Saída", "Faturamento", "M11"),
];
