import Guide from "./Guide";
import styles from "./Guide.module.css";

export default function GuideContent({ benchmark }: { benchmark?: string }): React.ReactNode {
  return <div className={styles.guide}><Guide benchmark={benchmark} /></div>;
}
