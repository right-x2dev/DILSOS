import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, api } from "../../api/client";
import { useInvalidate } from "../../api/hooks";
import { Button } from "../../components/ui";
import type { Scenario } from "../../types/api";

type ImportResult = { created_orders: string[]; lines: number };
type RowError = { row: number; field: string | null; message: string };

const TEMPLATE = "order_code,customer_code,release_local,due_local,priority,sku_code,qty\nNEW-001,C001,08:00,11:30,2,SKU001,3\nNEW-001,C001,08:00,11:30,2,SKU002,1\n";

/** Validated CSV import (POST /imports/orders). All-or-nothing: any row error → nothing imported. */
export function CsvImport({ sc }: { sc: Scenario }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const inv = useInvalidate();
  const m = useMutation({
    mutationFn: (f: File) => {
      const form = new FormData();
      form.append("scenario_id", String(sc.id));
      form.append("file", f);
      return api<ImportResult>("/imports/orders", { method: "POST", form });
    },
    onSuccess: () => inv(["orders"], ["scenarios"], ["dashboard"]),
  });
  const rowErrors = m.error instanceof ApiError && Array.isArray(m.error.details) ? (m.error.details as RowError[]) : [];
  function downloadTemplate() {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([TEMPLATE], { type: "text/csv" }));
    a.download = "dilsos_orders_template.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }
  return (
    <div className="space-y-2 text-sm">
      <p className="text-xs text-ink-600">
        열: order_code, customer_code, release_local(HH:MM), due_local(HH:MM), priority(1–3), sku_code, qty — 한 행 = 주문 라인. 시각은 {sc.facility.timezone} 운영일({sc.operating_date}) 기준. 최대 1MB, 오류가 하나라도 있으면 아무것도
        저장되지 않습니다.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input ref={fileRef} type="file" accept=".csv,text/csv" aria-label="CSV 파일" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-xs" />
        <Button onClick={() => file && m.mutate(file)} disabled={!file || m.isPending}>
          {m.isPending ? "검증·가져오는 중…" : "가져오기"}
        </Button>
        <Button variant="ghost" onClick={downloadTemplate}>
          템플릿 받기
        </Button>
      </div>
      {m.isSuccess && (
        <div className="rounded bg-emerald-50 p-2 text-xs text-emerald-800">
          주문 {m.data.created_orders.length}건 ({m.data.lines}개 라인) 생성: {m.data.created_orders.slice(0, 10).join(", ")}
          {m.data.created_orders.length > 10 ? " …" : ""}
        </div>
      )}
      {m.isError && (
        <div role="alert" className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          <div className="font-medium">{(m.error as Error).message}</div>
          {rowErrors.length > 0 && (
            <ul className="mt-1 max-h-40 overflow-auto">
              {rowErrors.map((e, i) => (
                <li key={i}>
                  행 {e.row}
                  {e.field ? ` [${e.field}]` : ""}: {e.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
