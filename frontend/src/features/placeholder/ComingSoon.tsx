import { PageHeader } from "../../components/ui";

/** Explicitly-labelled placeholder: never pretends a feature exists. */
export function ComingSoon({ title, phase }: { title: string; phase: string }) {
  return (
    <div>
      <PageHeader title={title} />
      <div className="rounded-lg border border-dashed border-ink-200 bg-white p-8 text-center">
        <div className="text-sm font-medium text-ink-800">준비 중 (Coming soon)</div>
        <div className="mt-1 text-xs text-ink-400">{phase}에서 구현 예정입니다. 이 화면에는 동작하는 컨트롤이 없습니다.</div>
      </div>
    </div>
  );
}
