#!/usr/bin/python
#
# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not
# use this file except in compliance with the License. A copy of the License
# is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, express or implied. See the License for the specific language
# governing permissions and limitations under the License.
#
#
# Search for AWS ParallelCluster public AMIs and generate a list in json and txt format
#
# usage: ./generate-ami-list.py --version <aws-parallelcluster-version> --date <release-date>

import argparse
import json
import sys
from collections import OrderedDict

import boto3
from botocore.exceptions import ClientError

distros = OrderedDict(
    [
        ("alinux", "amzn"),
        ("centos6", "centos6"),
        ("centos7", "centos7"),
        ("ubuntu1404", "ubuntu-1404"),
        ("ubuntu1604", "ubuntu-1604"),
    ]
)


def get_ami_list(regions, date, version, owner):
    amis_json = {}

    for region_name in regions:
        try:
            ec2 = boto3.client("ec2", region_name=region_name)
            images = ec2.describe_images(
                Owners=[owner], Filters=[{"Name": "name", "Values": ["aws-parallelcluster-%s*%s" % (version, date)]}]
            )

            amis = {}
            for image in images.get("Images"):
                for key, value in distros.items():
                    if value in image.get("Name"):
                        amis[key] = image.get("ImageId")

            if len(amis) == 0:
                print("Warning: there are no AMIs in the selected region (%s)" % region_name)
            else:
                amis_json[region_name] = OrderedDict(sorted(amis.items()))
        except ClientError:
            # skip regions on which we are not authorized (cn-north-1)
            pass

    return amis_json


def convert_json_to_txt(amis_json):
    amis_txt = ""
    for key, value in distros.items():
        amis_txt += "# " + key + "\n"
        for region, amis in amis_json.items():
            if key in amis:
                amis_txt += region + ": " + amis[key] + "\n"

    return amis_txt


def get_all_aws_regions(region):
    ec2 = boto3.client("ec2", region_name=region)
    return sorted(r.get("RegionName") for r in ec2.describe_regions().get("Regions"))


def update_cfn_template(cfn_template_file, amis_to_update):
    with open(cfn_template_file) as cfn_file:
        # object_pairs_hook=OrderedDict allows to preserve input order
        cfn_data = json.load(cfn_file, object_pairs_hook=OrderedDict)
    # update id for new amis without removing regions that are not in the amis_to_update dict
    current_amis = cfn_data.get("Mappings").get("AWSRegionOS2AMI")
    current_amis.update(amis_to_update)
    # enforce alphabetical regions order
    ordered_amis = OrderedDict(sorted(current_amis.items()))
    cfn_data.get("Mappings")["AWSRegionOS2AMI"] = ordered_amis
    with open(cfn_template_file, "w") as cfn_file:
        # setting separators to (',', ': ') to avoid trailing spaces after commas
        json.dump(cfn_data, cfn_file, indent=2, separators=(",", ": "))
        # add new line at the end of the file
        cfn_file.write("\n")

    # returns the updated amis dict
    return ordered_amis


def update_amis_txt(amis_txt_file, amis):
    amis_txt = convert_json_to_txt(amis_json=amis)
    with open(amis_txt_file, "w") as f:
        f.write("%s" % amis_txt)


if __name__ == "__main__":
    # parse inputs
    parser = argparse.ArgumentParser(
        description="Get public AWS ParallelCluster instances and generate a json and txt file"
    )
    parser.add_argument("--version", type=str, help="release version", required=True)
    parser.add_argument("--date", type=str, help="release date [timestamp] (e.g. 201801112350)", required=True)
    parser.add_argument("--txt-file", type=str, help="txt output file path", required=False, default="amis.txt")
    parser.add_argument("--partition", type=str, help="commercial | china | govcloud", required=True)
    parser.add_argument(
        "--cloudformation-template",
        type=str,
        help="path to cloudfomation template",
        required=False,
        default="cloudformation/aws-parallelcluster.cfn.json",
    )
    args = parser.parse_args()

    if args.partition == "commercial":
        account_id = "247102896272"
        region = "us-east-1"
    elif args.partition == "govcloud":
        account_id = "124026578433"
        region = "us-gov-west-1"
    elif args.partition == "china":
        account_id = "036028979999"
        region = "cn-north-1"
    else:
        print("Unsupported partition %s" % args.partition)
        sys.exit(1)

    regions = get_all_aws_regions(region)

    amis_dict = get_ami_list(regions=regions, date=args.date, version=args.version, owner=account_id)

    cfn_amis = update_cfn_template(cfn_template_file=args.cloudformation_template, amis_to_update=amis_dict)

    update_amis_txt(amis_txt_file=args.txt_file, amis=cfn_amis)
