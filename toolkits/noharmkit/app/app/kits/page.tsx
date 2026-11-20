import type { Metadata } from "next";

import { KitName, KitRow } from "@/components/kits/KitRow";
import styles from "@/components/kits/KitsPage.module.css";
import { NoharmLoop } from "@/components/kits/NoharmLoop";
import kits from "../../../../../docs/kits-data.json";

export const metadata: Metadata = { title: "Kits | ARISEKit" };

export default function KitsPage() {
  return (
    <main className={styles.page}>
      <div className={styles.content}>
        <h1 className={styles.title}><KitName name="ARISEKit" /></h1>
        <p className={styles.lede}>Start from an established benchmark format or build your own.</p>
        <section className={styles.feature} aria-labelledby="noharmkit-title">
          <div className={styles.featureCopy}>
            <p className={styles.label}>Recommended toolkit</p>
            <h2 id="noharmkit-title" className={styles.featureTitle}><KitName name="NOHARMKit" /></h2>
            <p className={styles.featureBody}>Score clinical recommendations by their potential to harm patients. Move from your own cases and clinician-reviewed rubrics to autograded responses and a model leaderboard.</p>
            <div className={styles.featureActions}>
              <a className={styles.primary} href="/noharm/welcome">Open NOHARMKit</a>
              <a className={styles.link} href="https://arxiv.org/abs/2512.01241" target="_blank" rel="noopener noreferrer">
                Paper ↗
              </a>
            </div>
          </div>
          <div className={styles.featureArt}><NoharmLoop /></div>
        </section>
        <section aria-labelledby="established-kits">
          <h2 id="established-kits" className={styles.heading}>Established Kits</h2>
          <ul className={styles.list}>
            {kits.filter(kit => kit.id !== "custom").map((kit) => <KitRow key={kit.id} kit={kit} />)}
          </ul>
        </section>
        <section className={styles.buildOwn} aria-labelledby="build-your-own">
          <h2 id="build-your-own" className={styles.heading}>Build Your Own</h2>
          <ul className={styles.list}>
            {kits.filter(kit => kit.id === "custom").map(kit => <KitRow key={kit.id} kit={kit} />)}
          </ul>
        </section>
      </div>
    </main>
  );
}
