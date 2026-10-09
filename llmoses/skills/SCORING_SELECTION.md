# Scores and selection

Larger penalized_score is better. It combines the current weighted behavioural
sum, complexity penalty, and uniformity penalty. `unweighted_score` is the sum
of the stored bscore vector; it remains comparable across row-weight changes.
The direct complexity coefficient is experiment-owned and clamped to [0,1].
Its legacy ratio alias maps positive r to clamp(1/r), and r<=0 to the ceiling 1.
The default ratio 3.5 retains coefficient 1/3.5. It is not an agent lever.

Exemplar selection uses the configured selection_temperature and native
INV_TEMP=100/selection_temperature. Do not confuse it with the separate native
deme trimming range or the agent sharpening temperature. Singleton selection
consumes no roulette RNG; the b=0 multi-member path consumes the native draw.

`selection` reports the selected program. `explored` means selected in a prior
generation. Lineage depth is inherited from the selected parent's depth plus
one for first-seen offspring. Primitive survivor/cull outcomes are emitted for
learning from previous decisions; no empirical utility estimator is hidden in
those outcomes. Ordered-set identity remains native tree identity.
