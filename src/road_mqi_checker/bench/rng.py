"""确定性随机源（合成数据生成器与基准的唯一随机入口）。

为什么不用 stdlib random：Python 不承诺其伪随机序列跨版本一致，
基准就会在另一台机器/另一个解释器上复现不出来。splitmix64 只有位运算，
任何解释器都算得一样，是"基准跨机器可复现"的地基。

同一条纪律还禁掉：set 迭代序、dict 依赖插入序以外的排序缺失、系统时钟入产物。
"""

from typing import List, Sequence

_MASK64 = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15


class SplitMix64(object):
    """64 位 splitmix 发生器：state 每次加黄金常数，再做异或-乘-异或-乘-异或。"""

    __slots__ = ("seed", "state")

    def __init__(self, seed):
        # type: (int) -> None
        if not isinstance(seed, int) or seed < 0:
            raise ValueError("seed 必须是非负整数，收到 %r" % (seed,))
        self.seed = seed
        self.state = seed & _MASK64

    def next_u64(self):
        # type: () -> int
        self.state = (self.state + _GOLDEN) & _MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
        return z ^ (z >> 31)

    def next_below(self, bound):
        # type: (int) -> int
        """均匀取 [0, bound)。取模偏差在本用途（数据形态抽样）可接受，
        但必须是纯函数式取模 —— 任何"更均匀"的实现都要保持位级一致，否则基准漂移。
        """
        if bound <= 0:
            raise ValueError("bound 必须为正，收到 %r" % (bound,))
        return self.next_u64() % bound

    def next_float(self):
        # type: () -> float
        """[0, 1) 双精度，用高 53 位构造 —— 位级可复现且不依赖舍入模式差异。"""
        return (self.next_u64() >> 11) * (1.0 / (1 << 53))

    def choice(self, sequence):
        # type: (Sequence) -> object
        if not sequence:
            raise ValueError("不能从空序列取样")
        return sequence[self.next_below(len(sequence))]

    def sample_without_replacement(self, population, k):
        # type: (Sequence, int) -> List
        """确定性无放回抽样：按下标交换，不引入 set 迭代序。"""
        if k < 0 or k > len(population):
            raise ValueError("k=%d 超出 population 长度 %d" % (k, len(population)))
        index = list(range(len(population)))
        picked = []  # type: List
        for i in range(k):
            j = i + self.next_below(len(index) - i)
            index[i], index[j] = index[j], index[i]
            picked.append(population[index[i]])
        return picked


def stream(seed, count):
    # type: (int, int) -> List[int]
    """纯函数版前 n 个 u64，供测试冻结向量与文档示例使用。"""
    rng = SplitMix64(seed)
    return [rng.next_u64() for _ in range(count)]
