import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CsvImport } from "../features/orders/CsvImport";
import { ExportButtons } from "../features/runs/ExportButtons";
import { RUN, SCENARIO } from "./fixtures";
import { renderWithProviders } from "./utils";

test("CSV import shows row-level validation errors from the API", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        error: {
          code: "import_validation_failed",
          message: "2 error(s); nothing was imported",
          details: [
            { row: 3, field: "customer_code", message: "unknown customer NOPE" },
            { row: 3, field: "release_local", message: "expected HH:MM" },
          ],
        },
      }),
      { status: 422, headers: { "content-type": "application/json" } },
    ),
  );
  renderWithProviders(<CsvImport sc={SCENARIO} />);
  const file = new File(["order_code\n"], "o.csv", { type: "text/csv" });
  await userEvent.upload(screen.getByLabelText("CSV 파일"), file);
  await userEvent.click(screen.getByRole("button", { name: "가져오기" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("nothing was imported");
  expect(alert).toHaveTextContent("행 3 [customer_code]: unknown customer NOPE");
  const [, init] = (globalThis.fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls[0];
  expect(init.body).toBeInstanceOf(FormData);
});

test("export buttons are disabled for unpublished runs", () => {
  renderWithProviders(<ExportButtons run={{ ...RUN, status: "FAILED" }} />);
  expect(screen.getByRole("button", { name: "CSV" })).toBeDisabled();
});

test("export downloads from the API for published runs", async () => {
  const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("record,run_id\n", { status: 200 }));
  globalThis.URL.createObjectURL = vi.fn(() => "blob:x");
  globalThis.URL.revokeObjectURL = vi.fn();
  renderWithProviders(<ExportButtons run={RUN} />);
  await userEvent.click(screen.getByRole("button", { name: "JSON" }));
  await waitFor(() => expect(spy).toHaveBeenCalled());
  expect(String(spy.mock.calls[0][0])).toContain("/exports/runs/7?format=json");
});
