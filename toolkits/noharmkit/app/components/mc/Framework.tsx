import { FRAMEWORK } from "@/components/mc/framework-copy";
import { Card } from "@/components/mc/ui";
import FrameworkIntro from "@/components/mc/FrameworkIntro";
import FrameworkRubric from "@/components/mc/FrameworkRubric";

export default function Framework() {
  return (
    <>
      <h1 className="m-0 text-[28px] font-semibold tracking-[-0.035em]">Framework</h1>
      <p className="m-0 mt-1 text-mc-muted">{FRAMEWORK.subtitle}</p>
      <Card className="mt-5 p-5 sm:p-6">
        <FrameworkIntro />
      </Card>
      <Card className="mt-4 p-5">
        <h2 className="m-0 mb-3 text-[15px] font-semibold">NOHARM core principles</h2>
        <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
          {FRAMEWORK.principles.map(([title, text]) => (
            <div key={title}>
              <b className="block text-sm">{title}</b>
              <p className="m-0 mt-1 text-[13.5px] leading-normal text-mc-muted">{text}</p>
            </div>
          ))}
        </div>
      </Card>
      <FrameworkRubric />
    </>
  );
}
