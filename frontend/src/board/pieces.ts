import bd from "@/assets/pieces/cburnett/bd.svg";
import bl from "@/assets/pieces/cburnett/bl.svg";
import kd from "@/assets/pieces/cburnett/kd.svg";
import kl from "@/assets/pieces/cburnett/kl.svg";
import nd from "@/assets/pieces/cburnett/nd.svg";
import nl from "@/assets/pieces/cburnett/nl.svg";
import pd from "@/assets/pieces/cburnett/pd.svg";
import pl from "@/assets/pieces/cburnett/pl.svg";
import qd from "@/assets/pieces/cburnett/qd.svg";
import ql from "@/assets/pieces/cburnett/ql.svg";
import rd from "@/assets/pieces/cburnett/rd.svg";
import rl from "@/assets/pieces/cburnett/rl.svg";

export type Colour = "w" | "b";
export type Role = "p" | "n" | "b" | "r" | "q" | "k";
export interface PieceInfo { colour: Colour; role: Role }

/** A piece set is one image per piece. The default is the BSD-licensed cburnett set; custom sets are plain folders served by the backend (later). */
export interface PieceSet { id: string; name: string; url(p: PieceInfo): string }

const CBURNETT: Record<string, string> = { wb: bl, wk: kl, wn: nl, wp: pl, wq: ql, wr: rl, bb: bd, bk: kd, bn: nd, bp: pd, bq: qd, br: rd };

export const PIECE_SETS: PieceSet[] = [{ id: "cburnett", name: "Classic", url: (p) => CBURNETT[p.colour + p.role] }];
export const DEFAULT_PIECE_SET = PIECE_SETS[0];
