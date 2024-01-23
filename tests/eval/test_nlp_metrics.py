# Copyright 2022 MosaicML Composer authors
# SPDX-License-Identifier: Apache-2.0


import torch

from llmfoundry.eval.metrics.nlp import ( InContextLearningCodeEvalAccuracy, InContextLearningLMAccuracy, InContextLearningMultipleChoiceAccuracy,
                                  InContextLearningQAAccuracy,)



def test_in_context_learning_lm_accuracy(tiny_gpt2_tokenizer):
    contexts = ['The dog is', 'I love to eat', 'I hate', 'The weather is']
    continuations = [' furry', ' pie', ' long lines', ' snowy']
    pad = tiny_gpt2_tokenizer.pad_token_id
    inputs = [
        tiny_gpt2_tokenizer(context)['input_ids'] + tiny_gpt2_tokenizer(continuation)['input_ids']
        for context, continuation in zip(contexts, continuations)
    ]
    inputs = torch.tensor([input + [pad] * (2048 - len(input)) for input in inputs])

    cont_idxs = []
    for context, continuation in zip(contexts, continuations):
        start = len(tiny_gpt2_tokenizer(context)['input_ids'])
        end = start + len(tiny_gpt2_tokenizer(continuation)['input_ids'])
        cont_idxs.append(torch.tensor(list(range(start, end))))

    batch = {'continuation_indices': cont_idxs, 'labels': inputs.roll(-1), 'input_ids': inputs}
    logits = torch.nn.functional.one_hot(inputs.roll(-1), num_classes=pad + 1).float() * 100
    start, end = cont_idxs[1].tolist()[0] - 1, cont_idxs[1].tolist()[-1]
    logits[1][start:end] = logits[0][start:end].clone()  # make one of the answer's continuations incorrect
    metric = InContextLearningLMAccuracy()
    metric.update(batch, logits, batch['labels'])

    assert metric.compute() == 0.75



def test_in_context_learning_qa_accuracy():
    outputs = ['Correct but then some more text', 'Incorrect', ' the CORREct with weird casing and spacing']
    labels = [['Correct'], ['blah', 'blah2'], ['blah', 'correct']]
    batch = {'cot_delimiter': '', 'labels': labels}
    metric = InContextLearningQAAccuracy()
    metric.update(outputs, labels, batch)

    assert metric.compute() == (2 / 3)


def test_in_context_learning_qa_cot_accuracy():
    outputs = [
        'chain of thought ### Correct but then some more text\n\nanother chain of thought ### Incorrect answer this time',
        'Incorrect', 'chain of thought ### the CORREct with weird casing and spacing',
        'incorrect chain of thought delimiter ## Correct but wrong delimiter'
    ]
    labels = [['Correct'], ['blah', 'blah2'], ['blah', 'correct'], ['correct']]
    batch = {'cot_delimiter': ' ### ', 'labels': labels, 'do_normalization': True, 'stopping_criteria': '\n\n'}
    metric = InContextLearningQAAccuracy()
    metric.update(outputs, labels, batch)

    assert metric.compute() == (2 / 4)


def test_in_context_learning_code_eval_accuracy(monkeypatch):
    outputs = [
        '    return 1 if n <= 1 else fib(n - 1) + fib(n - 1)',  # incorrect
        '   if n <= 1:\n        return 1\n    return fib(n-1) + fib(n-2)',  # incorrect spacing
        '    return n * 2',  # correct
        '    return 2*n',  # correct
        '    return n + 2',  # incorrect
        '    return n + 1'
    ]  # correct
    labels = []
    prompts = ['def fib(n):\n', 'def multiply_by_two(n):\n', 'def add_one(n):\n']
    entry_points = ['fib', 'multiply_by_two', 'add_one']
    test_inputs = [['(1,)', '(2,)', '(4,)'], ['(1,)', '(2,)', '(4,)'], ['(1,)', '(2,)', '(4,)']]
    test_outputs = [['1', '2', '5'], ['2', '4', '8'], ['2', '3', '5']]
    languages = ['python', 'python', 'python']
    monkeypatch.setenv('CODE_EVAL_DEVICE', 'LOCAL')
    batch = {
        # This tests deterministic beam search rather than sampling
        'generation_kwargs': {
            'num_beams': 1,
            'num_return_sequences': 2
        },
        'prompts': prompts,
        'pass_at_k': 1,
        'entry_points': entry_points,
        'test_inputs': test_inputs,
        'test_outputs': test_outputs,
        'languages': languages,
    }
    metric = InContextLearningCodeEvalAccuracy()
    metric.update(batch, outputs, labels)

    # pass@1 values
    #   program 1: 0
    #   program 2: 1
    #   program 3: .5
    # mean: 0.5
    assert metric.compute() == 0.5


def test_in_context_learning_mc_accuracy(tiny_gpt2_tokenizer):
    contexts = [
        'Q: How do you cook a cake?', 'Q: How do you cook a cake?', 'Q: How old is the earth?',
        'Q: How old is the earth?'
    ]
    continuations = [' A: turn on the oven', ' A: do a backflip', ' A: 2 minutes', ' A: 4.5 billion years']
    gold_indices = [0, 1]
    choice_groupings = [(0, 2), (2, 4)]
    pad = tiny_gpt2_tokenizer.pad_token_id
    inputs = [
        tiny_gpt2_tokenizer(context)['input_ids'] + tiny_gpt2_tokenizer(continuation)['input_ids']
        for context, continuation in zip(contexts, continuations)
    ]
    inputs = torch.tensor([input + [pad] * (2048 - len(input)) for input in inputs])

    cont_idxs = []
    for context, continuation in zip(contexts, continuations):
        start = len(tiny_gpt2_tokenizer(context)['input_ids'])
        end = start + len(tiny_gpt2_tokenizer(continuation)['input_ids'])
        cont_idxs.append(torch.tensor(list(range(start, end))))

    batch = {
        'continuation_indices': cont_idxs,
        'labels': inputs.roll(-1),
        'input_ids': inputs,
        'gold_indices': gold_indices,
        'choice_groupings': choice_groupings
    }
    logits = torch.nn.functional.one_hot(inputs.roll(-1), num_classes=pad + 1).float()

    # for the first two, the correct answer is continuation 0
    # make the answer correct by making continuation 0 more likely for both answers
    start, end = cont_idxs[1].tolist()[0] - 1, cont_idxs[1].tolist()[-1]
    logits[1][start:end] = logits[0][start:end].clone()

    # for the last two, the correct answer is continuation 3
    # make the answer incorrect by making continuation 2 more likely for both answers
    start, end = cont_idxs[3].tolist()[0], cont_idxs[3].tolist()[-1]
    logits[3][start:end] = logits[2][start:end].clone()

    metric = InContextLearningMultipleChoiceAccuracy()

    metric.update(batch, logits, batch['labels'])
    assert metric.compute() == 0.5
