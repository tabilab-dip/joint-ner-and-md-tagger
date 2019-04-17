import dynet
from collections import defaultdict
from itertools import chain
from matplotlib import pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

def concentration(embeddings):
    """

    calculate the concentration of embedding vectors as defined in Language Models Learn POS first

    :type embeddings: list
    :param embeddings:

    :return:
    """
    norms = [0, 0]
    c_array = []
    for vec in embeddings:
        print(vec)
        norms[0] = np.sum(np.abs(vec))
        norms[1] = np.sqrt(np.sum(np.square(vec)))
        c_array.append(norms[1]/norms[0])

    return np.array(c_array).reshape(1, -1)


def test_concentration():

    embeddings = [[1, 0, 0], [0, 1, 0]]

    c_array = concentration(embeddings)

    assert (c_array == np.array([[1, 1]])).all()


def test_dev_obtain_valid_paths():
    from collections import namedtuple

    model = namedtuple('model', ["entity_types"])
    model.entity_types = ["PER", "LOC"]

    from functools import partial
    model._obtain_valid_paths = partial(dev_obtain_valid_paths, model)

    valid_paths = list(model._obtain_valid_paths(4))

    assert len(valid_paths) == -1, valid_paths


def dev_obtain_valid_paths(self, sequence_length):

    if sequence_length == 0:
        # yield []
        pass # do not yield
    elif sequence_length == 1:
        for entity_type in self.entity_types:
            yield ["S-%s" % entity_type]
    else:
        for entity_type in self.entity_types:
            for right_valid_path in self._obtain_valid_paths(sequence_length - 1):
                yield ["S-%s" % entity_type] + right_valid_path
        for l in range(2, sequence_length+1):
            valid_path = [""] * l
            valid_path[0] = "B-%s"
            for i in range(1, l):
                valid_path[i] = "I-%s"
            valid_path[-1] = "E-%s"
            for entity_type in self.entity_types:
                for right_valid_path in self._obtain_valid_paths(sequence_length-l):
                    # yield ["tag1"] + right_valid_path
                    yield [(x % entity_type) for x in valid_path] + right_valid_path
                if l == sequence_length:
                    # yield ["tag2"] + [l, sequence_length]
                    yield [(x % entity_type) for x in valid_path]


import datetime as dt
import linecache
import os
from resource import getrusage, RUSAGE_SELF
import tracemalloc

def display_top(snapshot, key_type='lineno', limit=3):
    snapshot = snapshot.filter_traces((
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        tracemalloc.Filter(False, "<unknown>"),
    ))
    top_stats = snapshot.statistics(key_type)

    print("Top %s lines" % limit)
    for index, stat in enumerate(top_stats[:limit], 1):
        frame = stat.traceback[0]
        # replace "/path/to/module/file.py" with "module/file.py"
        filename = os.sep.join(frame.filename.split(os.sep)[-2:])
        print("#%s: %s:%s: %.1f KiB"
              % (index, filename, frame.lineno, stat.size / 1024))
        line = linecache.getline(frame.filename, frame.lineno).strip()
        if line:
            print('    %s' % line)

    other = top_stats[limit:]
    if other:
        size = sum(stat.size for stat in other)
        print("%s other: %.1f KiB" % (len(other), size / 1024))
    total = sum(stat.size for stat in top_stats)
    print("Total allocated size: %.1f KiB" % (total / 1024))


def generate_raw_explanations(args, data_dir):
    models = {
        "finnish_model_10_size": ("./xnlp/data/models",
                                 "model-00002218/",
                                 "model-epoch-00000030/"),
        "finnish_model_100_size": ("./models",
                                 "model-00002715/",
                                 "model-epoch-00000047/"),
        "turkish_model_100_size": ("./models",
                                   "model-00002714/",
                                   "model-epoch-00000026/"),
    }

    from utils.evaluation import do_xnlp

    model, data_dict, id_to_tag, word_to_id, stats_dict, id_to_char, id_to_morpho_tag, opts, parameters = \
        do_xnlp(
            *models[args.model_label],
            modify_paths_in_opts=False if args.on_truba else True
        )


    from lib.lime.lime.lime_text import LimeConllSentenceExplainer, ConllSentenceDomainMapper, IndexedConllSentence

    explainer = LimeConllSentenceExplainer(verbose=True, feature_selection="none")

    unique_morpho_tag_types = set(model.id_to_morpho_tag.values())

    morpho_tag_to_id = {k: i for i, k in model.id_to_morpho_tag.items()}

    with open(os.path.join(data_dir, "id_to_morpho_tag-for-ner-train-%s.txt" % args.model_label), "w") as out_id_to_morpho_tag_f:
        out_id_to_morpho_tag_f.write(
            "\t".join([" ".join(map(str, t)) for t in sorted(model.id_to_morpho_tag.items(), key=lambda x: x[0])]) + "\n")

    lime_explanations = []
    raw_explanations = []

    for sample_idx, sample in enumerate(data_dict['ner']['train']):
        max_rss = getrusage(RUSAGE_SELF).ru_maxrss

        print(dt.datetime.now(), 'max RSS', max_rss)

        indexed_conll_sentence = IndexedConllSentence(sample)
        domain_mapper = ConllSentenceDomainMapper(indexed_conll_sentence)
        from utils.evaluation import extract_multi_token_entities
        for entity_start, entity_end, entity_type in extract_multi_token_entities(
                [model.id_to_tag[i] for i in sample['tag_ids']]):
            entity_positions = (entity_start, entity_end)
            # extract the golden labels for the sequence
            entity_tags = [model.id_to_tag[i] for i in
                           sample['tag_ids'][entity_positions[0]:entity_positions[-1]]]

            morpho_tag_types_found_in_the_sample_as_ids = set().union(*[set().union(*[set(morpho_tag_sequence)
                                                                                      for morpho_tag_sequence in
                                                                                      morpho_tag_sequences])
                                                                        for morpho_tag_sequences in
                                                                        sample['morpho_analyzes_tags'][
                                                                        entity_positions[0]:entity_positions[-1]]])

            morpho_tag_types_found_in_the_sample = [model.id_to_morpho_tag[i] for i in
                                                    sorted(list(morpho_tag_types_found_in_the_sample_as_ids))]

            class_names = model.obtain_valid_paths(entity_end - entity_start)
            class_names = [x[1] for x in
                           sorted([(" ".join(class_name), class_name) for class_name in class_names],
                                  key=lambda x: x[0])]
            target_entity_tag_sequence_label_id = class_names.index(entity_tags)

            dynet.renew_cg()
            exp, configurations, probs = explainer.explain_instance(sample,
                                                                    entity_positions,
                                                                    class_names,
                                                                    model.probs_for_a_specific_entity,
                                                                    labels=(target_entity_tag_sequence_label_id,),
                                                                    num_samples=100,
                                                                    num_features=len(
                                                                        morpho_tag_types_found_in_the_sample_as_ids),
                                                                    strategy="NER_TAG_TYPE_REMOVAL",
                                                                    strategy_params_dict={
                                                                        "morpho_tag_types": sorted(
                                                                            list(
                                                                                morpho_tag_types_found_in_the_sample_as_ids)),
                                                                        "n_unique_morpho_tag_types": len(
                                                                            unique_morpho_tag_types),
                                                                        "perturbate_only_entity_indices": True
                                                                    }
                                                                    )

            lime_explanation_summary = "\t".join([str(sample_idx), entity_type, " ".join([str(x) for x in [entity_start, entity_end]])] +
                          [" ".join([x[0], str(x[1])]) for x in domain_mapper.translate_feature_ids_in_exp(
                              exp.local_exp[target_entity_tag_sequence_label_id],
                              morpho_tag_types_found_in_the_sample)]) + "\n"

            print(lime_explanation_summary)
            lime_explanations.append(lime_explanation_summary)

            one_liners = []
            for tmp in [configurations, probs]:
                out_string = ""
                out_string += "%d %d " % tmp.shape
                out_string += " ".join(["%e" % x for x in list(tmp.ravel())])
                one_liners.append(out_string)

            raw_explanation = "\t".join(one_liners
                                              + [str(target_entity_tag_sequence_label_id)]
                                              + [" ".join([str(len(model.id_to_morpho_tag))] + [str(x) for x in sorted(
                                        list(morpho_tag_types_found_in_the_sample_as_ids))])]) + "\n"

            raw_explanations.append(raw_explanation)

    return lime_explanations, raw_explanations


def explain_using_raw_probs(args, data_dir):

    files = {"all": "../../explanations-for-ner-train-finnish-20190114-total.txt",
             "only_target_entities": "../../explanations-for-ner-train-finnish-20190115-total-only_target_entities.txt",
             "finnish_model_10_size": {"explanations": "../../explanations-for-ner-train-finnish_model_10_size.txt",
                                       "raw_data": "../../regression-data-for-ner-train-finnish_model_10_size.txt"},
             "finnish_model_100_size": {"explanations": "explanations-for-ner-train-finnish_model_100_size.txt",
                                        "raw_data": "regression-data-for-ner-train-finnish_model_100_size.txt",
                                        "id_to_morpho_tag": "id_to_morpho_tag-for-ner-train-finnish_model_100_size.txt"},
             "turkish_model_100_size": {"explanations": "explanations-for-ner-train-turkish_model_100_size.txt",
                                        "raw_data": "regression-data-for-ner-train-turkish_model_100_size.txt",
                                        "id_to_morpho_tag": "id_to_morpho_tag-for-ner-train-turkish_model_100_size.txt"}}

    lines = []
    raw_data_records = []
    with open(os.path.join(data_dir, files[args.model_label]["raw_data"]), "r") as f:
        lines = f.readlines()
        for line in lines:
            first_part, second_part, third_part, fourth_part = line.strip().split("\t")

            size_x, size_y, *conf_data = [int(float(x)) for x in first_part.split(" ")]
            C = np.reshape(conf_data, (size_x, size_y))

            size_x, size_y, *probs_data = [float(x) for x in second_part.split(" ")]
            P = np.reshape(probs_data, (int(size_x), int(size_y)))

            target_class_index = int(third_part)

            n_morpho_tags, *morpho_tag_ids = [int(x) for x in fourth_part.split(" ")]

            record = (C, P, target_class_index, n_morpho_tags, morpho_tag_ids)
            raw_data_records.append(record)

    lines = []
    records = []
    with open(os.path.join(data_dir, files[args.model_label]["explanations"]), "r") as f:
        lines = f.readlines()
        for line in lines:
            tokens = line.strip().split("\t")
            record = [int(tokens[0]), tokens[1], tuple([int(x) for x in tokens[2].split(" ")])]
            record.append({k: float(v) for k, v in [tuple(x.split(" ")) for x in tokens[3:]]})
            records.append(record)

    # version without duplicates
    from collections import defaultdict

    zero_centered_Ps = defaultdict(list)
    indexed_Cs = defaultdict(list)
    for i in range(len(raw_data_records)):
        C = raw_data_records[i][0]
        P = raw_data_records[i][1]
        target_class_index = raw_data_records[i][2]
        n_morpho_tags = raw_data_records[i][3]
        morpho_tag_ids_per_sentence = raw_data_records[i][4]
        target_entity_type = records[i][1]

        unperturbated_configuration = [0] * n_morpho_tags
        for morpho_tag_id in morpho_tag_ids_per_sentence:
            unperturbated_configuration[morpho_tag_id] = 1
        #     indexed_C = [0]*n_morpho_tags
        #     for idx in range(len(indexed_C)):
        #         indexed_C[idx] = list(unperturbated_configuration)

        indexed_C = [list(unperturbated_configuration)]
        for idx in range(n_morpho_tags):
            tainted = False
            perturbated_configuration = list(unperturbated_configuration)
            for morpho_tag_idx, morpho_tag_id in enumerate(morpho_tag_ids_per_sentence):
                if idx == morpho_tag_id and unperturbated_configuration[morpho_tag_id] == 1:
                    perturbated_configuration[morpho_tag_id] = -1
                    tainted = True
            if tainted:
                indexed_C.append(perturbated_configuration)
        indexed_Cs[target_entity_type] += [np.array(indexed_C)]

        zero_centered_P = [0.0]
        for morpho_tag_id, diff_value in zip(morpho_tag_ids_per_sentence,
                                             list(P[1:, target_class_index] - P[0, target_class_index])):
            zero_centered_P.append(diff_value)
        zero_centered_Ps[target_entity_type] += [zero_centered_P]

    for target_entity_type in zero_centered_Ps.keys():
        zero_centered_Ps[target_entity_type] = np.array(zero_centered_Ps[target_entity_type])
        indexed_Cs[target_entity_type] = np.array(indexed_Cs[target_entity_type])

    with open(os.path.join(data_dir, files[args.model_label]["id_to_morpho_tag"]), "r") as id_to_morpho_tag_f:
        id_to_morpho_tag = {int(x.split(" ")[0]): x.split(" ")[1] for x in
                            id_to_morpho_tag_f.readline().strip().split("\t")}

    explanations = dict()
    for entity_type in zero_centered_Ps.keys():
        explanations[entity_type] = []
        for sentence_idx in range(indexed_Cs[entity_type].shape[0]):
            from sklearn.linear_model import Ridge

            reg_loc = Ridge(alpha=1, fit_intercept=False)

            cur_X = indexed_Cs[entity_type][sentence_idx]  # (89, 89)
            cur_Y = zero_centered_Ps[entity_type][sentence_idx]  # (89,)
            reg_loc.fit(cur_X, cur_Y)

            # print("sentence: %d, intercept: %lf", sentence_idx, reg_loc.intercept_)

            cur_explanation = sorted([(idx, id_to_morpho_tag[idx], value) for idx, value in
                                      zip(sorted(id_to_morpho_tag.keys()), reg_loc.coef_)],
                                     key=lambda x: x[2],
                                     reverse=True)
            cur_str_explanation = "\n".join(
                [" ".join((str(idx), morpho_tag, "%.7lf" % weight)) for idx, morpho_tag, weight in cur_explanation])
            #     print(cur_explanation)
            explanations[entity_type].append(cur_explanation)

    explanations_nparray_dict = {}
    for entity_type in zero_centered_Ps.keys():
        explanations_nparray_dict[entity_type] = np.array(
            [[t[2] for t in sorted(explanations[entity_type][i], key=lambda x: x[0])] for i in
             range(len(explanations[entity_type]))])

    return indexed_Cs, zero_centered_Ps, id_to_morpho_tag, explanations, explanations_nparray_dict


def generate_tables_in_latex(language_name, zero_centered_Ps, id_to_morpho_tag, explanations_nparray_dict):
    ret_dict = {}
    unfiltered_means = {}
    near_zero_groups_table = defaultdict(dict)
    zero_groups_table = defaultdict(dict)
    for entity_type in zero_centered_Ps.keys():
        mean_for_entity_type = sorted(
            [(id_to_morpho_tag[idx], el) for idx, el in enumerate(explanations_nparray_dict[entity_type].mean(axis=0))],
            key=lambda x: x[1], reverse=True)
        zero_means_for_entity_type = [x for x in mean_for_entity_type if x[1] == 0]
        near_zero_means_for_entity_type = [x for x in mean_for_entity_type if np.abs(x[1]) < 1e-6]
        list_to_be_added = [mean_for_entity_type[:10], mean_for_entity_type[-10:],
                            zero_means_for_entity_type,
                            near_zero_means_for_entity_type]
        list_to_be_added += list(chain.from_iterable(
            [[[x for x in mean_for_entity_type[:i] if x[1] != 0],
              [x for x in mean_for_entity_type[-i:] if x[1] != 0]] for i in range(1, 10)]))
        unfiltered_means[entity_type] = np.array([x[1] for x in mean_for_entity_type])
        ret_dict[entity_type] = list_to_be_added
        limited_mean_for_entity_type = mean_for_entity_type[:10] + mean_for_entity_type[-10:]
        df_results = pd.DataFrame([x for x in limited_mean_for_entity_type],
                                  index=[x[0] for x in limited_mean_for_entity_type])
        print("\\begin{table}")
        print(df_results.to_latex(header=["Morphological Tag", "Average Weight"], index=False))
        print("\\caption{Average weights over the corpus for %s %s entities\label{tab:%s_corpus_average}}" % (language_name, entity_type, entity_type.lower()))
        print("\\end{table}")
        print("")

        print(entity_type)
        print(mean_for_entity_type)

        # use zero_means_for_entity_type to determine zero_groups
        for feature_name, _ in zero_means_for_entity_type:
            zero_groups_table[feature_name][entity_type] = 1
        # use zero_means_for_entity_type to determine zero_groups
        for feature_name, _ in near_zero_means_for_entity_type:
            near_zero_groups_table[feature_name][entity_type] = 1

    zero_groups = defaultdict(list)
    for feature_name, active_entity_types in zero_groups_table.items():
        zero_groups["ZERO_GROUP_"+"_".join(sorted(active_entity_types.keys()))].append(feature_name)
    for zero_group_name, zero_group in zero_groups.items():
        ret_dict[zero_group_name] = ",".join(sorted(zero_groups[zero_group_name]))
    near_zero_groups = defaultdict(list)
    for feature_name, active_entity_types in near_zero_groups_table.items():
        near_zero_groups["NEAR_ZERO_GROUP_" + "_".join(sorted(active_entity_types.keys()))].append(feature_name)
    for zero_group_name, zero_group in near_zero_groups.items():
        ret_dict[zero_group_name] = ",".join(sorted(near_zero_groups[zero_group_name]))
    return ret_dict, unfiltered_means


def generate_tables_with_cumsum_in_latex(language_name, zero_centered_Ps, id_to_morpho_tag, explanations_nparray_dict):

    for entity_type in zero_centered_Ps.keys():
        mean_for_entity_type = sorted(
            [(id_to_morpho_tag[idx], el) for idx, el in enumerate(explanations_nparray_dict[entity_type].mean(axis=0))],
            key=lambda x: x[1], reverse=True)

        cumsum_positive_scaled = np.cumsum([x[1] for x in mean_for_entity_type if x[1] > 0])/np.sum([x[1] for x in mean_for_entity_type if x[1] > 0])
        cumsum_negative_scaled = np.cumsum([x[1] for x in reversed(mean_for_entity_type) if x[1] <= 0])/np.sum([x[1] for x in reversed(mean_for_entity_type) if x[1] <= 0])

        array_to_latex = [(el1[0], el2) for el1, el2 in zip(mean_for_entity_type,
                                                                    np.concatenate((cumsum_positive_scaled,
                                                                                    cumsum_negative_scaled[::-1])))]

        limited_mean_for_entity_type = array_to_latex[:10] + array_to_latex[-10:]
        df_results = pd.DataFrame([x for x in limited_mean_for_entity_type])
        print("\\begin{table}")
        print(df_results.to_latex(header=["Morphological Tag", "Normalized Cumsum"], index=False))
        print("\\caption{Average weights over the corpus for %s %s entities\label{tab:%s_corpus_average_cumsum_%s}}" % (language_name,
                                                                                                                 entity_type,
                                                                                                                 entity_type.lower(),
                                                                                                                 language_name.lower()))
        print("\\end{table}")
        print("")


def print_statistics_about_vector(unfiltered_means_for_entity_type):
    var = np.var(unfiltered_means_for_entity_type)
    mean = np.mean(unfiltered_means_for_entity_type)
    min = np.min(unfiltered_means_for_entity_type)
    max = np.max(unfiltered_means_for_entity_type)
    n_positive = len(np.where(unfiltered_means_for_entity_type > 0)[0])
    n_negative = len(np.where(unfiltered_means_for_entity_type < 0)[0])
    quantiles = [np.quantile(unfiltered_means_for_entity_type, q) for q in [0.1, 0.25, 0.5, 0.75, 0.9]]
    print("var: %lf" % var)
    print("mean: %lf" % mean)
    print("min, max: %lf, %lf" % (min, max))
    return [var, mean, min, max, n_positive, n_negative] + quantiles


def plot_histogram(unfiltered_means_for_entity_type_for_hist, plot_filename, width=0.0001):
    counts, edge_values = np.histogram(unfiltered_means_for_entity_type_for_hist, 25)
    plt.figure(figsize=(10, 2))
    plt.bar(list(edge_values), np.concatenate((counts, np.array([0]))), width=width)
    plt.title(plot_filename)
    plt.savefig(plot_filename)
    plt.close()
    print(plot_filename)
    print(len(unfiltered_means_for_entity_type_for_hist))
    print(counts)
    print(edge_values)
    return counts, edge_values


def generate_statistics_tables_in_latex(statistics, row_labels, column_labels):
    for entity_type in statistics.keys():
        values = statistics[entity_type]
        df_results = pd.DataFrame(np.array([list(row) for idx, row in enumerate(values)]),
                                  index=row_labels,
                                  columns=column_labels)

        print("\\begin{table}")
        print(df_results.to_latex(header=column_labels, formatters=[(lambda x: "%.02E" % x) for _ in range(len(column_labels))]))
        print("\\caption{Statistics for average weights over the corpus for %s %s entities\label{tab:%s_corpus_average_statistics_%s}}" % (
        language_name, entity_type, entity_type.lower(), language_name))
        print("\\end{table}")
        print("")

def generate_statistics_tables_over_entities_in_latex(statistics, row_labels, column_labels, start_index=0):
    entity_types = list(statistics.keys())
    index = pd.MultiIndex.from_product([entity_types, row_labels])
    values = []
    for idx, entity_type in enumerate(entity_types):
        values += [list(row)[start_index:(start_index+len(column_labels))] for _, row in enumerate(statistics[entity_type])]
    df_results = pd.DataFrame(np.array(values),
                              index=index,
                              columns=column_labels)

    print("\\begin{table}")
    print(df_results.to_latex(header=column_labels, formatters=[(lambda x: "%.02E" % x) for _ in range(len(column_labels))]))
    print("\\caption{Statistics for average weights over the corpus for %s ALL entities\label{tab:%s_corpus_average_statistics_all_entities}}" % (
    language_name, language_name))
    print("\\end{table}")
    print("")


class Node:

    def __init__(self, key, value):
        self.key = key
        self.value = value

        self.parents = []
        self.children_keys = {}
        self.children_nodes = {}

    def __eq__(self, other):
        return self.key == other.key

    @staticmethod
    def distance(left_node, right_node):

        def get_path_to_root(node):
            path = []
            while len(node.parents) != 0:
                path = [node.parents[0]] + path
                node = node.parents[0]
            return path

        left_path_to_root = get_path_to_root(left_node)
        right_path_to_root = get_path_to_root(right_node)

        level = 0
        while level < min(len(left_path_to_root), len(right_path_to_root)) and \
                left_path_to_root[level] == right_path_to_root[level]:
            level += 1

        d = len(left_path_to_root[level:]) + len(right_path_to_root[level:])
        return d


def iterate_over_training_set(args):
    models = {
        "finnish_model_10_size": ("./xnlp/data/models",
                                 "model-00002218/",
                                 "model-epoch-00000030/"),
        "finnish_model_100_size": ("./models",
                                 "model-00002715/",
                                 "model-epoch-00000047/"),
        "turkish_model_100_size": ("./models",
                                   "model-00002714/",
                                   "model-epoch-00000026/"),
    }

    from utils.evaluation import do_xnlp

    _, data_dict, _, _, _, _, _, _, _ = \
        do_xnlp(
            *models[args.model_label],
            modify_paths_in_opts=False if args.on_truba else True
        )

    for sample_idx, sample in enumerate(data_dict['ner']['train']):
        yield sample_idx, sample


def perturbate_tree_using_random_walk(args):

    # index = 0
    # root = Node("root", index)
    #
    # level1_nodes = [Node("level1_%d" %i, i) for i in range(5)]
    # for level1_node in level1_nodes:
    #     level1_node.parents.append(root)
    #     root.children_keys[level1_node.key] = 1
    #     root.children_nodes[level1_node.key] = level1_node
    #
    # level2_nodes = [Node("level2_1_%d" % i, i) for i in range(3)]
    # for level2_node in level2_nodes:
    #     level2_node.parents.append(level1_nodes[0])
    #     root.children_keys[level2_node.key] = 1
    #     root.children_nodes[level2_node.key] = level2_node
    #
    # level2_nodes = [Node("level2_2_%d" % i, i) for i in range(4)]
    # for level2_node in level2_nodes:
    #     level2_node.parents.append(level1_nodes[1])
    #     root.children_keys[level2_node.key] = 1
    #     root.children_nodes[level2_node.key] = level2_node
    #

    # from networkx.generators.trees import random_tree
    #
    # tree = random_tree(10)
    # from networkx.drawing.nx_pylab import draw
    # draw(tree)
    # import matplotlib.pyplot as plt
    # plt.show()

    it = iterate_over_training_set(args)

    first_tuple = next(it)

    first_sentence = first_tuple[1]

    # data_item = {
    #     'str_words': surface_forms,
    #
    #     'word_ids': words,
    #     'char_for_ids': chars,
    #     'cap_ids': caps,
    #
    #     'morpho_analyzes_tags': morph_analyses_tags,
    #     'morpho_analyzes_roots': morph_analyses_roots,
    #
    #     'char_lengths': [len(char) for char in chars],
    #     'sentence_lengths': len(sentence),
    #     'max_word_length_in_this_sample': max([len(x) for x in chars])
    # }

    import networkx as nx

    G = nx.Graph()
    nodes = {}
    root_node = 0
    nodes[root_node] = {'node_color': 'r'}
    cur_index = 0
    for pos, char_seq in enumerate(first_sentence['char_for_ids']):
        cur_index += 1
        nodes[cur_index] = {'node_color': 'r'}
        G.add_edge(root_node, cur_index)
        parent_index = cur_index
        for char_pos, char_value in enumerate(char_seq):
            cur_index += 1
            nodes[cur_index] = {'node_color': 'r'}
            G.add_edge(parent_index, cur_index)

    nodes[3]['node_color'] = 'b'

    from networkx.drawing.nx_pylab import draw
    draw(G, node_color=[x[1]['node_color'] for x in sorted(nodes.items(), key=lambda x:x[0])])
    import matplotlib.pyplot as plt
    plt.show()





if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument("--command", required=True)
    parser.add_argument("--model_label", required=True)
    parser.add_argument("--on_truba", default=False)

    args = parser.parse_args()

    data_dir = "./toolkit/xnlp/"

    if args.command == "generate_explanations":
        lime_explanations, raw_explanations = generate_raw_explanations(args, data_dir)
        with open(os.path.join(data_dir, "explanations-for-ner-train-%s.txt" % args.model_label), "w") as out_f, \
                open(os.path.join(data_dir, "regression-data-for-ner-train-%s.txt" % args.model_label), "w") as regression_data_f:
            for line in lime_explanations:
                out_f.write(line)
            for line in raw_explanations:
                regression_data_f.write(line)
    elif args.command == "explain_using_raw_probs":
        indexed_Cs, zero_centered_Ps, id_to_morpho_tag, explanations, explanations_nparray_dict = \
            explain_using_raw_probs(args, data_dir)
        language_name = args.model_label.split("_")[0]
        language_name = language_name[0].upper() + language_name[1:]
        top_and_bottom_morpho_tags_dict, unfiltered_means = generate_tables_in_latex(language_name,
                                                                                     zero_centered_Ps,
                                                                                     id_to_morpho_tag,
                                                                                     explanations_nparray_dict)
        from itertools import chain
        for entity_type, top_and_bottom_morpho_tags in top_and_bottom_morpho_tags_dict.items():
            if entity_type.startswith("ZERO_GROUP_") or entity_type.startswith("NEAR_ZERO_GROUP_"):
                print("%s=%s" % (entity_type, top_and_bottom_morpho_tags))
            else:
                for idx, label in enumerate(["top", "bottom", "zero", "near_zero"] +
                                            list(chain.from_iterable(zip(["top%02d" % i for i in range(1, 10)],
                                                                         ["bottom%02d" % i for i in range(1, 10)])))):
                    print("%s_morpho_tags_%s=%s" % (entity_type, label, ",".join([str(x[0]) for x in top_and_bottom_morpho_tags[idx]])))
        print("")



        import matplotlib.pyplot as plt
        statistics = defaultdict(list)
        means_by_type = defaultdict(list)
        entity_types = unfiltered_means.keys()
        for entity_type in entity_types:
            unfiltered_means_for_entity_type = unfiltered_means[entity_type]
            statistics[entity_type].append(print_statistics_about_vector(unfiltered_means_for_entity_type))

            positive_side = np.array([x for x in unfiltered_means_for_entity_type if x > 0])
            statistics[entity_type].append(print_statistics_about_vector(positive_side))
            plot_histogram(positive_side,
                           "%s-%s-positive-side-histogram.png" % (language_name,
                                                                         entity_type))
            negative_side = np.array([x for x in unfiltered_means_for_entity_type if x < 0])
            statistics[entity_type].append(print_statistics_about_vector(negative_side))
            plot_histogram(negative_side,
                           "%s-%s-negative-side-histogram.png" % (language_name,
                                                                  entity_type))

            positive_side_scaled = positive_side / np.max(positive_side)
            statistics[entity_type].append(print_statistics_about_vector(positive_side_scaled))
            plot_histogram(positive_side_scaled,
                           "%s-%s-positive-side-scaled-histogram.png" % (language_name,
                                                                  entity_type),
                           width=0.001)

            negative_side_scaled = negative_side / np.min(negative_side)
            statistics[entity_type].append(print_statistics_about_vector(negative_side_scaled))
            plot_histogram(negative_side_scaled,
                           "%s-%s-negative-side-scaled-histogram.png" % (language_name,
                                                                         entity_type),
                           width=0.001)

            for zeros in ["on", "off"]:
                plot_filename = "%s-%s-means-histogram-zeros-%s.png" % (language_name, entity_type, zeros)
                if zeros == "off":
                    unfiltered_means_for_entity_type_for_hist = [x for x in unfiltered_means_for_entity_type
                                                        if np.abs(x) > 10e-6]
                else:
                    unfiltered_means_for_entity_type_for_hist = unfiltered_means_for_entity_type
                counts, edge_values = plot_histogram(unfiltered_means_for_entity_type_for_hist, plot_filename)
                # sns_plot = sns.distplot(unfiltered_means_for_entity_type, 50)
                #fig = sns_plot.get_figure()
                # fig.savefig(plot_filename)

                # counts, edge_values = np.histogram(unfiltered_means_for_entity_type, 50)
                # plt.bar(edge_values, counts)
                # plt.savefig(plot_filename)
                print("%s\n%s\n%s" % (entity_type,
                                      language_name,
                                      plot_filename))

            print("XXXX unchanged: %s" % str(unfiltered_means_for_entity_type.shape))
            means_by_type["unchanged"] += [unfiltered_means_for_entity_type]
            print("XXXX positive_side: %s" % str(positive_side.shape))
            means_by_type["positive"] += [np.concatenate((positive_side, [np.nan] * (len(unfiltered_means_for_entity_type)-len(positive_side))))]
            means_by_type["negative"] += [np.concatenate((negative_side, [np.nan] * (len(unfiltered_means_for_entity_type)-len(negative_side))))]
            means_by_type["positive_scaled"] += [np.concatenate((positive_side_scaled, [np.nan] * (len(unfiltered_means_for_entity_type)-len(positive_side_scaled))))]
            means_by_type["negative_scaled"] += [np.concatenate((negative_side_scaled, [np.nan] * (len(unfiltered_means_for_entity_type)-len(negative_side_scaled))))]

        for mean_type in "unchanged positive negative positive_scaled negative_scaled".split(" "):
            print(mean_type)
            print(np.array(means_by_type[mean_type]).shape)
            _df = pd.DataFrame(np.array(means_by_type[mean_type]).T, columns=entity_types)
            plt.figure()
            _df.boxplot()
            title = "boxplot-%s_%s_corpus_average_statistics_all_entities.png" % (language_name, mean_type)
            plt.title(title)
            plt.savefig(title)
            plt.close()


        generate_statistics_tables_in_latex(statistics,
                                            "unchanged positive negative positive_scaled negative_scaled".split(" "),
                                            "var mean min max n_positive n_negative".split(" ")
                                            + ["q%.02lf" % q for q in [0.1, 0.25, 0.5, 0.75, 0.9]])
        generate_statistics_tables_over_entities_in_latex(statistics,
                                                          "unchanged positive negative positive_scaled negative_scaled".split(" "),
                                                          "var mean min max n_positive n_negative".split(" "))
        generate_statistics_tables_over_entities_in_latex(statistics,
                                                          "unchanged positive negative positive_scaled negative_scaled".split(" "),
                                                          ["q%.02lf" % q for q in [0.1, 0.25, 0.5, 0.75, 0.9]],
                                                          start_index=6)

        generate_tables_with_cumsum_in_latex(language_name,
                                 zero_centered_Ps,
                                 id_to_morpho_tag,
                                 explanations_nparray_dict)
        # print(id_to_morpho_tag)
    elif args.command == "perturbate_tree":
        perturbate_tree_using_random_walk(args)
