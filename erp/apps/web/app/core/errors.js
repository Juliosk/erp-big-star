// Mensagens de erro da API em português (reaproveitadas do front anterior).
export const ERRORS = {
  VERSION_CONFLICT:
    "Outra alteração foi salva. Atualize o detalhe antes de tentar novamente.",
  BARCODE_CONFLICT: "Este código de barras já existe na empresa.",
  PRODUCT_IDENTIFIER_CONFLICT:
    "Código ou SKU já cadastrado. Confira os identificadores.",
  CUSTOMER_DUPLICATE_EXACT_MATCH:
    "CPF/CNPJ já cadastrado para a empresa selecionada.",
  CUSTOMER_GROUP_CONFLICT: "Grupo de clientes já cadastrado nesta empresa.",
  CUSTOMER_GROUP_MEMBER_CONFLICT: "Este cliente já pertence ao grupo.",
  CUSTOMER_MERGE_REQUEST_CONFLICT:
    "Já existe uma solicitação pendente para este par de clientes.",
  INVENTORY_NEGATIVE_BALANCE:
    "O ajuste deixaria saldo negativo. Revise quantidade, lote e depósito.",
  MINIMUM_MARGIN_VIOLATION:
    "A margem projetada está abaixo da política mínima da empresa.",
  PRICE_NOT_FOUND:
    "Nenhum preço ativo foi encontrado para o produto e lista informados.",
  STANDARD_COST_NOT_FOUND:
    "Cadastre um custo padrão provisório para simular ou resolver o preço.",
  INVALID_PRICE_LIST_VERSION_STATUS:
    "A versão da lista não está em situação compatível com esta ação.",
  PRICING_PRICE_LIST_CONFLICT:
    "Já existe uma lista de preços com este código na empresa selecionada.",
  PRICING_PRICE_LIST_VERSION_CONFLICT:
    "Outra alteração foi salva nesta versão de lista. Atualize antes de ativar.",
  PRICING_UNAVAILABLE: "Pricing indisponível nesta inicialização.",
  PRICING_RESOLUTION_UNAVAILABLE:
    "Resolução de pricing indisponível nesta inicialização.",
  PRICING_SIMULATION_UNAVAILABLE:
    "Simulação de pricing indisponível nesta inicialização.",
  PRICING_SNAPSHOTS_UNAVAILABLE:
    "Consulta de snapshots indisponível nesta inicialização.",
  WMS_BARCODE_MISMATCH:
    "Código de barras não corresponde ao produto da tarefa.",
  WMS_PACKAGE_EMPTY:
    "Adicione ao menos um item antes de verificar o pacote.",
  WMS_PACKAGE_ITEM_MISMATCH:
    "O item do pacote não corresponde à tarefa de separação.",
  WMS_PACKAGE_OVER_PACK:
    "A quantidade embalada excede a quantidade já bipada.",
  WMS_PACKAGE_STATUS_CONFLICT:
    "O pacote não está em uma situação compatível com esta ação.",
  WMS_PICKING_TASK_NOT_PICKED:
    "Bipe a tarefa antes de adicionar o item ao pacote.",
  WMS_PICKING_TASK_OVER_PICK:
    "A bipagem excede a quantidade solicitada na tarefa.",
  WMS_PICKING_WAVE_STATUS_CONFLICT:
    "A onda não está em uma situação compatível com esta ação.",
  WMS_PACKING_UNAVAILABLE: "Packing WMS indisponível nesta inicialização.",
  PERMISSION_FORBIDDEN: "Sua identidade não tem permissão para esta ação.",
  RESOURCE_NOT_FOUND: "Cadastro não encontrado na empresa selecionada.",
  INVALID_LIFECYCLE_TRANSITION:
    "Esta transição não é permitida para a situação atual.",
  AUTHENTICATION_UNAVAILABLE:
    "Configure o adapter de identidade. Em local/test, habilite DEV_AUTH_ENABLED e configure token, ator e empresas.",
  AUTHENTICATION_REQUIRED: "Token inválido ou expirado. Conecte-se novamente.",
  INVALID_BARCODE: "Código inválido. Confira o formato e o dígito verificador.",
  IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD:
    "A tentativa anterior possui dados diferentes. Revise o formulário.",
  VALIDATION_ERROR: "Confira os campos obrigatórios e seus formatos.",
  BUSINESS_VALIDATION_ERROR: "Os dados não atendem às regras do cadastro.",
  SUPPLIER_CONFLICT: "Já existe um fornecedor com este documento na empresa.",
  SOD_VIOLATION:
    "A segregação de funções impede a autoaprovação desta solicitação.",
  PAYABLE_DIVERGENCE_BLOCKED:
    "Divergências fiscais ou de compras precisam ser resolvidas antes desta ação.",
  PAYABLE_APPROVAL_REQUIRED:
    "Este título ainda depende da aprovação de alçada no M22.",
  PAYABLE_APPROVAL_POLICY_NOT_CONFIGURED:
    "A política de alçada financeira não está configurada para esta empresa.",
  FINANCE_PAYABLE_UNAVAILABLE:
    "O serviço de contas a pagar está indisponível nesta inicialização.",
  FINANCE_TREASURY_UNAVAILABLE:
    "O serviço de tesouraria está indisponível nesta inicialização.",
  PAYMENT_BATCH_REVIEW_BLOCKED:
    "O lote possui divergências pendentes. Consulte a fila explicável antes de gerar a remessa.",
  DRY_RUN_BATCH_NOT_EXECUTABLE:
    "Este lote é somente simulação e não pode gerar uma remessa oficial.",
  FISCAL_SEFAZ_UNAVAILABLE:
    "O gateway SEFAZ não está configurado para este ambiente.",
  FISCAL_CANCELLATION_WINDOW_EXPIRED:
    "A janela legal de cancelamento deste documento expirou.",
  FISCAL_CANCELLATION_REJECTED:
    "A SEFAZ rejeitou o evento de cancelamento. Consulte o histórico.",
  FISCAL_DOCUMENT_NOT_EXPORTABLE:
    "O documento ainda não possui artefato fiscal oficial para exportação.",
  FISCAL_STORAGE_UNAVAILABLE:
    "O armazenamento fiscal está temporariamente indisponível.",
  FISCAL_INBOUND_CONFLICT:
    "Este XML de entrada já foi registrado para a empresa selecionada.",
  GOODS_RECEIPT_NOT_INSPECTED:
    "O recebimento precisa concluir a inspeção M17 antes da conciliação.",
  RECONCILIATION_ALREADY_EXISTS:
    "Esta nota fiscal já possui uma conciliação registrada.",
  RECONCILIATION_POSTING_INCOMPLETE:
    "Todos os itens conciliados precisam estar aprovados para saldo disponível.",
  UNSUPPORTED_MEDIA_TYPE: "Selecione um arquivo XML válido do fornecedor.",
};
