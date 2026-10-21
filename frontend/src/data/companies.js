export function createCompanyChats(companies = []) {
  return companies.map((company) => ({
    id: `company-${company.stock_code}`,
    title: company.name,
    stockCode: company.stock_code,
    messages: [],
  }));
}
