export type NavItem = { to: string; label: string; en: string };

export const NAV: NavItem[] = [
  { to: "/", label: "대시보드", en: "Overview" },
  { to: "/scenarios", label: "시나리오", en: "Scenarios" },
  { to: "/orders", label: "주문·자원", en: "Orders" },
  { to: "/optimize", label: "최적화 실행", en: "Optimize" },
  { to: "/gantt", label: "창고 간트", en: "Gantt" },
  { to: "/docks", label: "도크 타임라인", en: "Docks" },
  { to: "/routes", label: "배송 경로", en: "Routes" },
  { to: "/journey", label: "통합 타임라인", en: "Journey" },
  { to: "/disruptions", label: "교란 시뮬레이터", en: "Disrupt" },
  { to: "/compare", label: "알고리즘 비교", en: "Compare" },
  { to: "/runs", label: "실행 이력·감사", en: "Runs" },
];
