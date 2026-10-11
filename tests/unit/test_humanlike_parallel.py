import numpy as np
import pytest
import torch

from chessme.humanlike import models as MD
from chessme.humanlike import score as S
from chessme.humanlike import testset as T
from chessme.model import net
from tests.unit.test_humanlike_testset import make_game
from tests.unit.test_model_train import TINY


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory):
    path = tmp_path_factory.mktemp("ck") / "net.pt"
    torch.manual_seed(7)
    net.save_checkpoint(path, net.MeNet(TINY))
    return path


@pytest.fixture(scope="module")
def items():
    ps = []
    for i in range(30):
        ps += T.game_positions(make_game(site=f"par{i:06d}"), per_game=3, seed=4)
    return T.to_items(ps)


def test_the_rows_are_the_same_for_any_number_of_workers_and_any_chunking(checkpoint, items):
    kw = {"spec": f"ours={checkpoint}"}
    one, name1 = S.score_items_parallel(kw, items, workers=1)
    two, name2 = S.score_items_parallel(kw, items, workers=2, chunk_items=7)
    assert name1 == name2 and len(one["p"]) == len(items) == len(two["p"])
    for key in ("rank", "n_legal", "topk_move", "top1"):
        assert np.array_equal(one[key], two[key]), key                       # same order, same moves
    for key in ("p", "conf", "entropy", "sq_sum", "topk_p"):
        assert np.allclose(one[key], two[key], atol=1e-5), key              # one thread vs several may differ in the last bits only


def test_progress_reaches_the_total(checkpoint, items):
    seen = []
    S.score_items_parallel({"spec": f"ours={checkpoint}"}, items, workers=2, chunk_items=10, progress=lambda d, n: seen.append((d, n)))
    assert seen[-1] == (len(items), len(items)) and [d for d, _ in seen] == sorted(d for d, _ in seen)


def test_the_factory_rejects_unknown_specs():
    with pytest.raises(SystemExit, match="unknown scorer"):
        MD.make_scorer("gpt=4")
